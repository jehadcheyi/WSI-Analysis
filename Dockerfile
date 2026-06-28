FROM nvidia/cuda:11.8.0-cudnn8-devel-ubuntu22.04

RUN apt-get update && apt-get install -y \
    python3.10 python3-pip python3-dev \
    openslide-tools libopenslide-dev \
    git curl build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN ln -sf python3.10 /usr/bin/python3 && ln -sf python3 /usr/bin/python

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pipeline deps
RUN pip install --no-cache-dir \
    openslide-python scikit-image scikit-learn tqdm \
    huggingface_hub psutil umap-learn hdbscan reportlab \
    "transformers>=4.37.0" einops einops-exts safetensors \
    timm==1.0.3 \
    git+https://github.com/Mahmoodlab/CONCH.git

COPY . .
RUN mkdir -p uploads results model

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
