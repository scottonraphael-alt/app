"""Télécharge le modèle ONNX quantifié au moment du build de l'image,
pour éviter de le retélécharger à chaque démarrage du container."""
from huggingface_hub import snapshot_download

snapshot_download(
    repo_id="KoalaAI/Text-Moderation",
    local_dir="/app/model",
    allow_patterns=["*.onnx", "*.json", "*.txt"],
)
