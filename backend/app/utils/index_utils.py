import logging
import os

import requests

logger = logging.getLogger(__name__)

def search_papers_via_api(api_url, query, search_strategy='tf-idf', similarity_cutoff=0.1, filters=None):
    """Search papers using the /find_similar/ endpoint for a single query.
    Returns a list of paper dictionaries corresponding to the results.
    """
    # 根据新的API结构构建payload
    payload = {
        "query": query,
        "top_k": 3,
        "similarity_cutoff": similarity_cutoff,
        "search_strategies": [(search_strategy, 0.5)],  # 新API使用元组格式 (strategy, threshold)
        "filters": filters,
        "result_include_types": ["metadata", "text_chunks"]  # 使用正确的结果类型
    }
    try:
        response = requests.post(f"{api_url}/find_similar/", json=payload, timeout=30.0)
        response.raise_for_status()
        results = response.json()
        logger.info(f"搜索结果数量: {len(results)} for query '{query}'")
        return results
    except Exception as e:
        logger.error(f"搜索论文失败 '{query}': {e}")
        return []

def get_openai_client(base_url="http://10.0.1.226:5666/v1", api_key="EMPTY"):
    """Legacy: kept for backward compatibility with batch_update endpoint."""
    from openai import OpenAI
    return OpenAI(
        base_url=base_url,
        api_key=api_key
    )

def get_users_with_empty_rewrite_interest(backend_api="http://localhost:8000/api/users"):
    """获取所有rewrite_interest为空的用户"""
    resp = requests.get(f"{backend_api}/rewrite_interest/empty")
    return resp.json()

_TRANSLATE_PROMPT = """You are an expert bilingual rewriter specializing in English and Chinese.
Your job is to produce a clear, information-rich English query for semantic search or dense retrieval.

When given an input in either Chinese or English:
- If it's in Chinese, translate it into fluent, natural English.
- If it's already in English, keep it in English.
- In both cases, rewrite or expand it slightly to make the user's intent explicit and unambiguous.
- Focus on preserving the meaning, not literal translation.
- Do NOT add explanations, metadata, or prefixes like "Translation:".
- Output only the final English text.
"""


def translate_text_gemini(text: str, api_key: str | None = None) -> str | None:
    """Translate/rewrite research interests to English using Gemini."""
    from google import genai

    if api_key is None:
        api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY not set, cannot translate")
        return None

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-3.1-flash-lite-preview",
            contents=f"{_TRANSLATE_PROMPT}\n\nUser input:\n{text}",
        )
        return response.text.strip() if response.text else None
    except Exception as e:
        logger.error(f"Gemini translation failed: {e}")
        return None


def translate_text(client, text):
    """Legacy translate using OpenAI-compatible client (DeepSeek). Kept for batch_update endpoint."""
    try:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": _TRANSLATE_PROMPT},
                {"role": "user", "content": f"{text}"}
            ],
            max_tokens=512
        )
        output = resp.choices[0].message.content
        return output
    except Exception as e:
        logger.error(f"Translation failed: {e}")
        return None

def batch_update_rewrite_interest(users_data, backend_api="http://localhost:8000/api/users"):
    """批量更新用户的rewrite_interest字段"""
    resp = requests.post(f"{backend_api}/rewrite_interest/batch_update", json=users_data)
    return resp.json()

def update_single_user_rewrite_interest(username, research_interests_text, backend_api="http://localhost:8000/api/users", openai_base_url="http://10.0.1.226:5666/v1", api_key="EMPTY"):
    """
    为单个用户更新rewrite_interest字段

    Args:
        username: 用户名
        research_interests_text: 用户的研究兴趣文本（中文）
        backend_api: 后端API地址
        openai_base_url: OpenAI API地址
        api_key: OpenAI API密钥

    Returns:
        更新结果
    """
    # 检查输入
    if not research_interests_text or not isinstance(research_interests_text, str) or not research_interests_text.strip():
        print(f"用户 {username} 的research_interests_text为空或无效，跳过翻译")
        return {"updated": []}

    # 初始化客户端
    client = get_openai_client(openai_base_url, api_key)

    # 翻译
    english_text = translate_text(client, research_interests_text)
    if not english_text:
        print(f"用户 {username} 的研究兴趣翻译失败")
        return {"updated": []}

    # 更新单个用户（使用批量接口）
    update_data = [{
        "username": username,
        "rewrite_interest": english_text
    }]

    result = batch_update_rewrite_interest(update_data, backend_api)
    print(f"用户 {username} 的rewrite_interest更新结果: {result}")
    return result

def rewrite_user_interests(backend_api="http://localhost:8000/api/users", openai_base_url="http://10.0.1.226:5666/v1", api_key="EMPTY"):
    """主函数：获取用户、翻译并更新"""
    # 初始化客户端
    client = get_openai_client(openai_base_url, api_key)

    # 获取用户
    users = get_users_with_empty_rewrite_interest(backend_api)

    batch_updates = []

    # 处理每个用户
    for user in users:
        # 只翻译 research_interests_text 字段
        text_to_translate = user.get("research_interests_text")
        if text_to_translate and isinstance(text_to_translate, str) and text_to_translate.strip():
            # 翻译
            english_text = translate_text(client, text_to_translate)
            if english_text:
                batch_updates.append({
                    "username": user["username"],
                    "rewrite_interest": english_text
                })

    # 批量更新
    if batch_updates:
        result = batch_update_rewrite_interest(batch_updates, backend_api)
        print(f"批量写入结果：{result}")
        return result
    else:
        print("没有需要更新的用户。")
        return {"updated": []}

if __name__ == "__main__":
    # 直接运行时执行主函数
    rewrite_user_interests()
