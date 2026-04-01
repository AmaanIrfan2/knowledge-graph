#!/usr/bin/env python3
import asyncio
import logging
import sys

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s — %(message)s")
logger = logging.getLogger(__name__)


async def run(url: str) -> None:
    import db
    import scraper
    import extractor

    conn = await db.get_conn()
    await db.init_db(conn)

    # Dedup check
    existing_hash = await db.already_ingested(conn, url)
    if existing_hash:
        logger.info("Already ingested: %s", existing_hash)
        await conn.close()
        return

    # 1. Scrape
    logger.info("Scraping %s ...", url)
    article = await scraper.scrape(url)
    logger.info("Scraped: %s", article["headline"])

    # 1.5. Detect language and translate if Bangla
    from langdetect import detect, LangDetectException
    import translator

    headline_original = None
    body_text_original = None
    reporters_original = None
    language = "en"

    try:
        language = detect(article["body_text"])
    except LangDetectException:
        pass

    if language == "bn":
        logger.info("Bangla article detected — translating to English ...")
        headline_original = article["headline"]
        body_text_original = article["body_text"]
        reporters_original = article["reporters"]
        article["headline"] = translator.translate_bn_to_en(article["headline"])
        article["body_text"] = translator.translate_bn_to_en(article["body_text"])
        article["reporters"] = [translator.translate_bn_to_en(r) for r in article["reporters"]]
        logger.info("Translation complete.")

    # 2. Save article
    article_hash = await db.save_article(
        conn,
        source_url=url,
        source_name=article["source_name"],
        publish_dt=article["publish_dt"],
        headline=article["headline"],
        body_text=article["body_text"],
        reporters=article["reporters"],
        media_urls=article["media_urls"],
        language=language,
        headline_original=headline_original,
        body_text_original=body_text_original,
        reporters_original=reporters_original,
    )
    logger.info("Saved article: %s", article_hash)

    # 3. Extract entities and relations
    logger.info("Running Gemini extraction ...")
    elements, relations = await extractor.extract(article["body_text"])
    logger.info("Extracted %d elements, %d relations", len(elements), len(relations))

    # 4. Save KG data
    await db.save_elements_and_relations(conn, article_hash, elements, relations)
    logger.info("Done. Hash: %s", article_hash)

    await conn.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python ingest.py <url>")
        sys.exit(1)

    asyncio.run(run(sys.argv[1]))
