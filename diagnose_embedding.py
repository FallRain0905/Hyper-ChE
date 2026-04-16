#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
诊断嵌入API配置问题
"""

import sys
import json
from pathlib import Path

# Fix Windows encoding issue
if sys.platform == 'win32':
    import io as sys_io
    sys.stdout = sys_io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = sys_io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

def check_embedding_config():
    """检查嵌入配置"""
    print("🔍 检查嵌入API配置\n")

    settings_file = Path(__file__).parent / 'web-ui' / 'backend' / 'settings.json'

    if not settings_file.exists():
        print("❌ 设置文件不存在:", settings_file)
        print("💡 请先在设置页面配置API和嵌入模型")
        return False

    try:
        with open(settings_file, 'r', encoding='utf-8') as f:
            settings = json.load(f)

        print("📋 当前配置:")
        print("=" * 60)

        # 检查聊天模型配置
        print("\n📱 聊天模型配置:")
        print(f"  模型提供商: {settings.get('modelProvider', '未设置')}")
        print(f"  模型名称: {settings.get('modelName', '未设置')}")
        print(f"  Base URL: {settings.get('baseUrl', '未设置')}")
        print(f"  API Key: {settings.get('apiKey', '未设置')[:20]}..." if settings.get('apiKey') else "  API Key: 未设置")

        # 检查嵌入模型配置
        print("\n🧠 嵌入模型配置:")
        print(f"  嵌入模型: {settings.get('embeddingModel', '未设置')}")
        print(f"  嵌入维度: {settings.get('embeddingDim', '未设置')}")
        print(f"  嵌入API提供商: {settings.get('embeddingProvider', '未设置')}")

        # 检查独立的嵌入API配置
        embedding_provider = settings.get('embeddingProvider', 'same')
        if embedding_provider == 'custom':
            print(f"  嵌入Base URL: {settings.get('embeddingBaseUrl', '未设置')}")
            print(f"  嵌入API Key: {settings.get('embeddingApiKey', '未设置')[:20]}..." if settings.get('embeddingApiKey') else "  嵌入API Key: 未设置")
        else:
            print(f"  使用聊天模型相同的API配置")

        print("\n" + "=" * 60)

        # 诊断问题
        issues = []

        # 检查API Key
        api_key = settings.get("embeddingApiKey", settings.get("apiKey"))
        if not api_key:
            issues.append("❌ API Key未设置")
        elif len(api_key) < 10:
            issues.append("⚠️  API Key可能不完整")
        else:
            print("✅ API Key已设置")

        # 检查Base URL
        base_url = settings.get("embeddingBaseUrl", settings.get("baseUrl"))
        if not base_url:
            issues.append("❌ Base URL未设置")
        elif not base_url.startswith('http'):
            issues.append("⚠️  Base URL格式可能不正确")
        else:
            print("✅ Base URL已设置")

        # 检查嵌入模型
        embedding_model = settings.get("embeddingModel")
        if not embedding_model:
            issues.append("❌ 嵌入模型未设置")
        else:
            print(f"✅ 嵌入模型: {embedding_model}")

        # 检查模型和API的兼容性
        if embedding_model and base_url:
            model_provider = detect_model_provider(embedding_model, base_url)

            if model_provider == 'bailian':
                print("📌 检测到阿里云百炼模型")
                if not base_url.startswith('https://dashscope.aliyuncs.com'):
                    issues.append(f"⚠️  阿里云百炼模型应使用: https://dashscope.aliyuncs.com/compatible-mode/v1")
                    print(f"   当前: {base_url}")

                if not api_key or not api_key.startswith('sk-'):
                    issues.append("❌ 阿里云百炼需要以'sk-'开头的API Key")

            elif model_provider == 'siliconflow':
                print("📌 检测到硅基流动模型")
                if not base_url.startswith('https://api.siliconflow.cn'):
                    issues.append(f"⚠️  硅基流动模型应使用: https://api.siliconflow.cn/v1")
                    print(f"   当前: {base_url}")

                if not api_key or not api_key.startswith('sk-'):
                    issues.append("❌ 硅基流动需要以'sk-'开头的API Key")

            elif model_provider == 'openai':
                print("📌 检测到OpenAI模型")
                if not base_url.startswith('https://api.openai.com'):
                    issues.append("⚠️  OpenAI模型建议使用官方API地址")

        print("\n" + "=" * 60)

        if issues:
            print("⚠️  发现以下问题:")
            for issue in issues:
                print(f"  {issue}")

            print("\n💡 解决方案:")
            print("1. 访问设置页面 (/Setting)")
            print("2. 检查并更新API配置")
            print("3. 确保使用正确的API Key和Base URL")
            print("4. 检查模型名称是否正确")

            return False
        else:
            print("✅ 配置检查通过！")
            print("\n🔧 如果仍然出现403错误，可能的原因:")
            print("  1. API Key无效或过期")
            print("  2. API配额用完")
            print("  3. 网络连接问题")
            print("  4. API服务临时不可用")
            return True

    except Exception as e:
        print(f"❌ 读取配置失败: {str(e)}")
        return False

def detect_model_provider(embedding_model: str, base_url: str) -> str:
    """检测模型提供商"""
    if 'text-embedding-v' in embedding_model or 'qwen3-embedding' in embedding_model:
        return 'bailian'
    elif 'Qwen/Qwen2.5-Embedding' in embedding_model or 'Qwen2.5-Embedding' in embedding_model:
        return 'siliconflow'
    elif 'text-embedding-' in embedding_model and base_url:
        if 'dashscope' in base_url:
            return 'bailian'
        elif 'siliconflow' in base_url:
            return 'siliconflow'
        return 'openai'
    return 'unknown'

def test_api_connection():
    """测试API连接"""
    print("\n🧪 测试API连接\n")

    try:
        import asyncio
        from hyperrag.llm import openai_embedding

        async def test():
            # 读取配置
            settings_file = Path(__file__).parent / 'web-ui' / 'backend' / 'settings.json'
            with open(settings_file, 'r', encoding='utf-8') as f:
                settings = json.load(f)

            embedding_model = settings.get("embeddingModel", "text-embedding-3-small")
            api_key = settings.get("embeddingApiKey", settings.get("apiKey"))
            base_url = settings.get("embeddingBaseUrl", settings.get("baseUrl"))

            print(f"测试配置:")
            print(f"  模型: {embedding_model}")
            print(f"  API Key: {api_key[:20] if api_key else '未设置'}...")
            print(f"  Base URL: {base_url}")

            # 测试嵌入
            test_texts = ["这是一个测试文本，用于验证API连接。"]
            print(f"\n🚀 开始测试嵌入...")

            result = await openai_embedding(
                test_texts,
                model=embedding_model,
                api_key=api_key,
                base_url=base_url,
            )

            print(f"✅ API连接成功！")
            print(f"   嵌入维度: {result.shape[1]}")
            print(f"   嵌入结果: {result[0][:5]}... (前5个值)")

            return True

        return asyncio.run(test())

    except Exception as e:
        print(f"❌ API连接测试失败: {str(e)}")
        print(f"\n💡 可能的原因:")
        print(f"  1. API Key无效或格式错误")
        print(f"  2. Base URL配置错误")
        print(f"  3. 模型名称不正确")
        print(f"  4. 网络连接问题")
        print(f"  5. API服务权限问题")
        return False

def main():
    """主诊断函数"""
    print("=" * 60)
    print("嵌入API配置诊断")
    print("=" * 60)

    config_ok = check_embedding_config()

    if config_ok:
        print("\n" + "=" * 60)
        connection_ok = test_api_connection()

        if connection_ok:
            print("\n🎉 所有检查通过！API配置正常。")
            print("=" * 60)
            return 0
        else:
            print("\n" + "=" * 60)
            print("⚠️  API连接失败，请检查配置。")
            print("=" * 60)
            return 1
    else:
        print("\n" + "=" * 60)
        print("❌ 配置检查失败，请修复配置问题。")
        print("=" * 60)
        return 1

if __name__ == "__main__":
    sys.exit(main())