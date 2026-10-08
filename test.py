from src.config import get_settings

settings = get_settings()

print("GROQ_API_KEY:", settings.groq_api_key)
print("TAVILY_API_KEY:", settings.tavily_api_key)
print("PINECONE_API_KEY:", settings.pinecone_api_key)
print("PINECONE_INDEX_NAME:", settings.pinecone_index_name)
print("PINECONE_NAMESPACE:", settings.pinecone_namespace)
print("EMBEDDING_MODEL:", settings.embedding_model)