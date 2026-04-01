"""
Bangla → English translation using Helsinki-NLP/opus-mt-bn-en.
Model is loaded lazily on first use.
"""
import logging
import os
import re

logger = logging.getLogger(__name__)

_MODEL_NAME = os.getenv("TRANSLATION_MODEL", "Helsinki-NLP/opus-mt-bn-en")
_MAX_CHUNK_CHARS = 1000  # safe upper bound (~400–500 Bangla tokens per chunk)

_tokenizer = None
_model = None


def _load() -> None:
    global _tokenizer, _model
    if _tokenizer is not None:
        return
    from transformers import MarianMTModel, MarianTokenizer
    logger.info("Loading translation model %s ...", _MODEL_NAME)
    _tokenizer = MarianTokenizer.from_pretrained(_MODEL_NAME)
    _model = MarianMTModel.from_pretrained(_MODEL_NAME)
    logger.info("Translation model loaded.")


def _split_chunks(text: str) -> list[str]:
    """Split text into paragraph-level chunks that fit the model's 512-token limit."""
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    chunks: list[str] = []

    for para in paragraphs:
        if len(para) <= _MAX_CHUNK_CHARS:
            chunks.append(para)
        else:
            # Split long paragraphs on Bangla/common sentence-ending punctuation
            sentences = re.split(r"(?<=[।?!])\s+", para)
            current = ""
            for sent in sentences:
                if len(current) + len(sent) + 1 <= _MAX_CHUNK_CHARS:
                    current = (current + " " + sent).strip()
                else:
                    if current:
                        chunks.append(current)
                    current = sent
            if current:
                chunks.append(current)

    return chunks or [text]


def translate_bn_to_en(text: str) -> str:
    """
    Translate Bangla text to English.
    Returns the original text unchanged if it is empty.
    """
    if not text or not text.strip():
        return text

    _load()
    chunks = _split_chunks(text)
    translated: list[str] = []

    for chunk in chunks:
        inputs = _tokenizer(
            [chunk],
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=512,
        )
        outputs = _model.generate(**inputs)
        translated.append(_tokenizer.decode(outputs[0], skip_special_tokens=True))

    return "\n\n".join(translated)
