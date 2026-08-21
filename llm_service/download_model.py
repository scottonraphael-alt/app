"""Té·°lé·°charge le modè·°le Qwen2.5-0.5B-Instruct quantifié·© (GGUF Q4_K_M)
au moment du build de l'image."""
from huggingface_hub import hf_hub_download

hf_hub_download(
    repo_id="Qwen/Qwen2.5-0.5B-Instruct-GGUF",
    filename="qwen2.5-0.5b-instruct-q4_k_m.gguf",
    local_dir="/app/model",
)
