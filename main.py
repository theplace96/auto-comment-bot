import requests
import base64
import time
import threading
import os
from playwright.sync_api import sync_playwright

# ==========================
# 환경 변수 설정
# ==========================
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
WP_URL = os.getenv("WP_URL")

CATEGORY_ACCOUNTS = {
    11: {"username": "happyfox49", "password": "happyfox49"},  # 생활정보
    22: {"username": "coolbear95", "password": "coolbear95"},  # 대출
    23: {"username": "bravefox28", "password": "bravefox28"},  # 세금
    24: {"username": "mightymonkey56", "password": "mightymonkey56"}  # 지원금
}

comment_lock = threading.Lock()


# ==========================
# 워드프레스 인증 및 데이터 처리
# ==========================
def get_auth_headers(username, password):
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def get_posts_by_category(category_id, username, password):
    url = f"{WP_URL}/wp-json/wp/v2/posts?categories={category_id}&per_page=1"
    res = requests.get(url, headers=get_auth_headers(username, password))
    if res.status_code == 200:
        try:
            return res.json()
        except:
            return []
    return []


def get_existing_comments(post_id, username, password):
    url = f"{WP_URL}/wp-json/wp/v2/comments?post={post_id}&per_page=100"
    res = requests.get(url, headers=get_auth_headers(username, password))
    if res.status_code == 200:
        try:
            return res.json()
        except:
            return []
    return []


def has_user_commented(post_id, username, password):
    comments = get_existing_comments(post_id, username, password)
    for c in comments:
        if c.get("author_name", "").lower() == username.lower():
            return True
    return False


def post_comment(post_id, comment_text, username, password):
    url = f"{WP_URL}/wp-json/wp/v2/comments"
    headers = get_auth_headers(username, password)
    headers["Content-Type"] = "application/json"
    data = {"post": post_id, "content": comment_text}
    res = requests.post(url, headers=headers, json=data)
    return res.status_code == 201


# ==========================
# GPT API
# ==========================
def gpt(prompt):
    r = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "model": "gpt-3.5-turbo",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.8
        }
    )
    if r.status_code == 200:
        return r.json()["choices"][0]["message"]["content"].strip()
    else:
        print(f"❌ GPT 오류: {r.status_code}, {r.text}")
        return None


# ==========================
# 질문 문장 생성
# ==========================
def make_question_from_post(title, content):
    prompt = f"""
다음 글의 제목과 내용을 참고해서, 네이버 검색에 입력했을 때 AI 검색결과가 잘 나올법한 질문문장을 한 문장으로 만들어줘.
답변 없이 질문문장만 출력해.
제목: {title}
내용: {content}
"""
    return gpt(prompt)


# ==========================
# 질문 문장 변형 (AI 안 나올 때)
# ==========================
def reformulate_question(original_question, attempt):
    prompt = f"""
다음 질문을 네이버 AI 검색결과가 잘 나올 수 있게 다른 방식으로 다시 표현해줘.
질문의 의미는 그대로 유지해.
질문만 한 줄로 출력해.
원래 질문: {original_question}
시도 횟수: {attempt}
"""
    return gpt(prompt)


# ==========================
# 네이버 AI 검색 크롤링
# ==========================
def crawl_naver_ai_answer(keyword):
    url = f"https://search.naver.com/search.naver?query={keyword}"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=15000)

            ai_div_selector = "div.R_zhtndIdtnrHycLbDdg._slog_visible"

            try:
                page.wait_for_selector(ai_div_selector, timeout=10000)
            except:
                browser.close()
                return None

            try:
                more_btn = page.query_selector(f"{ai_div_selector} >> button:has-text(\"더보기\")")
                if more_btn:
                    more_btn.click()
            except:
                pass

            time.sleep(5)

            ai_div = page.query_selector(ai_div_selector)
            if not ai_div:
                browser.close()
                return None

            page.evaluate("""
            (element) => {
                element.querySelectorAll('a').forEach(a => a.remove());
                element.querySelectorAll('br').forEach(br => br.replaceWith('\\n'));
            }
            """, ai_div)

            text = page.evaluate("""
            (element) => {
                function getText(node) {
                    if(node.nodeType === Node.TEXT_NODE) return node.textContent;
                    return Array.from(node.childNodes).map(getText).join('');
                }
                return getText(element).replace(/\\n+/g, '\\n').trim();
            }
            """, ai_div)

            browser.close()
            return text if text else None
    except Exception as e:
        print(f"❌ 네이버 크롤링 오류: {e}")
        return None


# ==========================
# AI 검색 결과 반복 시도
# ==========================
def get_ai_search_result_with_retries(initial_question, max_attempts=5):
    question = initial_question
    for attempt in range(1, max_attempts + 1):
        print(f"🔄 네이버 AI 검색 시도 {attempt}: {question}")
        result = crawl_naver_ai_answer(question)
        if result:
            return question, result
        question = reformulate_question(question, attempt)
        if not question:
            break
        time.sleep(2)
    return None, None


# ==========================
# GPT로 댓글 문장 다듬기
# ==========================
def polish_answer_with_gpt(question, ai_text):
    prompt = f"""
다음은 네이버 AI 검색 결과입니다.
이 내용을 바탕으로, 질문에 대해 사람이 댓글로 한 문장으로 확신있게 답하는 형식으로 정리해줘.
추상적인 표현은 쓰지 말고, 정보와 이유를 같이 제시해.
질문: {question}
AI 결과: {ai_text}
"""
    return gpt(prompt)


# ==========================
# 카테고리별 봇 실행
# ==========================
def run_bot_for_category(category_id):
    account = CATEGORY_ACCOUNTS.get(category_id)
    if not account:
        return

    print(f"🚀 카테고리 {category_id} 댓글봇 시작")

    while True:
        posts = get_posts_by_category(category_id, account["username"], account["password"])
        if not isinstance(posts, list):
            time.sleep(60)
            continue

        for post in posts:
            post_id = post.get("id")
            title = post.get("title", {}).get("rendered", "")
            content = post.get("content", {}).get("rendered", "")

            if not post_id or not title:
                continue

            if has_user_commented(post_id, account["username"], account["password"]):
                continue

            print(f"📝 새 글 발견: {title}")

            with comment_lock:
                time.sleep(5)

                q = make_question_from_post(title, content)
                if not q:
                    continue

                final_q, ai_text = get_ai_search_result_with_retries(q)
                if not ai_text:
                    continue

                comment = polish_answer_with_gpt(final_q, ai_text)
                if not comment:
                    continue

                if post_comment(post_id, comment, account["username"], account["password"]):
                    print(f"✅ 댓글 작성 성공: {comment}")
                    time.sleep(10)


# ==========================
# 메인 실행
# ==========================
if __name__ == "__main__":
    threads = []
    for cat_id in CATEGORY_ACCOUNTS.keys():
        t = threading.Thread(target=run_bot_for_category, args=(cat_id,))
        t.start()
        threads.append(t)

    for t in threads:
        t.join()
