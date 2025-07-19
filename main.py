import requests
import base64
import time
import threading
import os

CATEGORY_ACCOUNTS = {
    11: {"username": "happyfox49", "password": "happyfox49"},  # 생활정보 커뮤니티
    22: {"username": "coolbear95", "password": "coolbear95"},  # 대출 커뮤니티
    23: {"username": "bravefox28", "password": "bravefox28"},  # 세금 커뮤니티
    24: {"username": "mightymonkey56", "password": "mightymonkey56"}  # 지원금 커뮤니티
}

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
WP_URL = os.getenv("WP_URL")

comment_lock = threading.Lock()  # 댓글 작성 락 생성

def get_auth_headers(username, password):
    credentials = f"{username}:{password}"
    token = base64.b64encode(credentials.encode()).decode()
    return {
        "Authorization": f"Basic {token}"
    }

def get_posts_by_category(category_id, username, password):
    url = f"{WP_URL}/wp-json/wp/v2/posts?categories={category_id}&per_page=1"
    headers = get_auth_headers(username, password)
    res = requests.get(url, headers=headers)
    if res.status_code == 200:
        try:
            return res.json()
        except Exception as e:
            print(f"응답 JSON 변환 실패: {e}")
            return []
    else:
        print(f"워드프레스 글 불러오기 실패, 상태 코드: {res.status_code}, 내용: {res.text}")
        return []

def get_existing_comments(post_id, username, password):
    url = f"{WP_URL}/wp-json/wp/v2/comments?post={post_id}&per_page=100"
    headers = get_auth_headers(username, password)
    res = requests.get(url, headers=headers)
    if res.status_code == 200:
        try:
            return res.json()
        except Exception as e:
            print(f"댓글 JSON 변환 실패: {e}")
            return []
    else:
        print(f"댓글 불러오기 실패: 상태 코드 {res.status_code}, 내용: {res.text}")
        return []

def has_user_commented(post_id, username, password):
    comments = get_existing_comments(post_id, username, password)
    for comment in comments:
        author_name = comment.get("author_name", "")
        if author_name.lower() == username.lower():
            return True
    return False

def generate_comment(title, content):
    prompt = f"""
게시글 제목
{title}

내용
{content}

이 글에 사람이 댓글 다는 것처럼 친근한 말투를 섞어서 딱 한 문장으로 단정적으로 말해줘

반드시 지켜야 할 조건은 다음과 같아
- 참고해보세요, 도움이 되었으면 좋겠어요, 검토해보세요 이런 당연하고 추상적인 말 절대 쓰지 마
- 근거와 이유를 토대로 실제 정보를 확신 있게 말해
- 애매한 표현 없이 말해
- 한 문장으로 끝내
"""

    res = requests.post(
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

    if res.status_code == 200:
        comment = res.json()["choices"][0]["message"]["content"].strip()
        # 따옴표로 감싸져 있을 경우 제거
        if (comment.startswith('"') and comment.endswith('"')) or (comment.startswith("'") and comment.endswith("'")):
            comment = comment[1:-1].strip()
        return comment
    else:
        print(f"OpenAI API 오류: {res.status_code}, 내용: {res.text}")
        return "댓글 생성에 실패했습니다."


def post_comment(post_id, comment_text, username, password):
    url = f"{WP_URL}/wp-json/wp/v2/comments"
    headers = get_auth_headers(username, password)
    headers["Content-Type"] = "application/json"
    data = {
        "post": post_id,
        "content": comment_text
    }
    res = requests.post(url, headers=headers, json=data)
    if res.status_code == 201:
        return True
    else:
        print(f"댓글 작성 실패: 상태 코드 {res.status_code}, 내용: {res.text}")
        return False

def run_bot_for_category(category_id):
    account = CATEGORY_ACCOUNTS.get(category_id)
    if not account:
        print(f"❌ 계정 없음: 카테고리 {category_id}")
        return

    print(f"실시간 댓글 봇 시작 - 카테고리 {category_id}")

    while True:
        posts = get_posts_by_category(category_id, account["username"], account["password"])

        if not isinstance(posts, list):
            print("❌ 글 목록이 리스트 형태가 아닙니다. API 응답 확인 필요.")
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

            print(f"🔍 새 글 발견: {title}")

            with comment_lock:  # 락 획득 후 댓글 작성 시작
                print("댓글 작성 전 30초 대기 중...")
                time.sleep(30)  # 댓글 달기 전에 30초 대기
                comment = generate_comment(title, content)
                if post_comment(post_id, comment, account["username"], account["password"]):
                    print(f"✅ 댓글 작성 성공 by {account['username']}")
                    time.sleep(10)  # 댓글 작성 후 10초 텀 유지
                else:
                    print(f"⚠️ 댓글 실패")

if __name__ == "__main__":
    threads = []
    for cat_id in CATEGORY_ACCOUNTS.keys():
        thread = threading.Thread(target=run_bot_for_category, args=(cat_id,))
        thread.start()
        threads.append(thread)

    for thread in threads:
        thread.join()
