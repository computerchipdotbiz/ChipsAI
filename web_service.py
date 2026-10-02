"""
ChipAI Web Browsing & Tech Reseller Scraping Engine
Provides live web search, webpage scraping, and dedicated tech reseller inventory monitoring
for Newegg, CDW, B&H Photo, Micro Center, Insight, Provantage, Connection, and NVIDIA Direct.
"""

import re
import json
import base64
import logging
import urllib.request
import urllib.parse
import urllib.error
from typing import List, Dict, Any, Optional
from bs4 import BeautifulSoup

logger = logging.getLogger("chipai.web_service")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "identity",
    "DNT": "1",
    "Upgrade-Insecure-Requests": "1",
}

TECH_RESELLERS = [
    {
        "name": "Newegg",
        "domain": "newegg.com",
    },
    {
        "name": "CDW",
        "domain": "cdw.com",
    },
    {
        "name": "B&H Photo Video",
        "domain": "bhphotovideo.com",
    },
    {
        "name": "Micro Center",
        "domain": "microcenter.com",
    },
    {
        "name": "Insight",
        "domain": "insight.com",
    },
    {
        "name": "Provantage",
        "domain": "provantage.com",
    },
    {
        "name": "Connection",
        "domain": "connection.com",
    },
    {
        "name": "NVIDIA Direct",
        "domain": "nvidia.com",
    },
]


def _unwrap_bing_url(raw_url: str) -> str:
    """Unwrap Bing redirect URL to direct destination."""
    if "bing.com/ck/a" in raw_url:
        try:
            parsed = urllib.parse.parse_qs(urllib.parse.urlparse(raw_url).query)
            u_param = parsed.get("u", [""])[0]
            if u_param.startswith("a1"):
                b64 = u_param[2:] + "=" * (-len(u_param[2:]) % 4)
                decoded = base64.b64decode(b64).decode("utf-8", errors="ignore")
                return decoded
        except Exception:
            pass
    return raw_url


def _clean_redirect_url(raw_url: str) -> str:
    """Clean and unwrap search engine redirect links to get the direct merchant/destination URL."""
    if not raw_url:
        return ""

    if "bing.com/ck/a" in raw_url:
        return _unwrap_bing_url(raw_url)

    # DuckDuckGo uddg parameter
    if "uddg=" in raw_url:
        try:
            parsed = urllib.parse.parse_qs(urllib.parse.urlparse(raw_url).query)
            if "uddg" in parsed:
                return parsed["uddg"][0]
        except Exception:
            pass

    # Bing/DDG ad wrapper with base64 encoded destination in 'u' or 'u3'
    if "duckduckgo.com/y.js" in raw_url or "bing.com/aclick" in raw_url:
        try:
            parsed = urllib.parse.parse_qs(urllib.parse.urlparse(raw_url).query)
            u3 = parsed.get("u3", [""])[0]
            target_query = u3 if u3 else raw_url
            p_sub = urllib.parse.parse_qs(urllib.parse.urlparse(target_query).query)
            raw_b64 = p_sub.get("u", [""])[0]
            if raw_b64:
                raw_b64 += "=" * (-len(raw_b64) % 4)
                decoded = urllib.parse.unquote(base64.b64decode(raw_b64).decode("utf-8", errors="ignore"))
                if decoded.startswith("http"):
                    split_q = decoded.split("?")[0]
                    return split_q if split_q else decoded
        except Exception:
            pass

    return raw_url


def search_bing(query: str, max_results: int = 6) -> List[Dict[str, str]]:
    """Search via Bing and unwrap direct URLs."""
    url = f"https://www.bing.com/search?q={urllib.parse.quote(query)}"
    results = []
    try:
        req = urllib.request.Request(url, headers=DEFAULT_HEADERS)
        with urllib.request.urlopen(req, timeout=12) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
            soup = BeautifulSoup(html, "html.parser")

            for item in soup.select("li.b_algo"):
                h2 = item.find("h2")
                p = item.find("p")
                if not h2:
                    continue

                title = h2.get_text(strip=True)
                snippet = p.get_text(strip=True) if p else ""
                a_tag = h2.find("a")
                raw_href = a_tag.get("href", "") if a_tag else ""
                clean_href = _clean_redirect_url(raw_href)

                if clean_href and title:
                    results.append({"title": title, "snippet": snippet, "url": clean_href})

                if len(results) >= max_results:
                    break

        return results
    except Exception as e:
        logger.warning(f"Bing search error for '{query}': {e}")
        return []


def search_duckduckgo(query: str, max_results: int = 6) -> List[Dict[str, str]]:
    """Search via DuckDuckGo HTML."""
    url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
    results = []
    try:
        req = urllib.request.Request(url, headers=DEFAULT_HEADERS)
        with urllib.request.urlopen(req, timeout=12) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
            soup = BeautifulSoup(html, "html.parser")

            for item in soup.select(".result"):
                title_elem = item.select_one(".result__title a")
                snippet_elem = item.select_one(".result__snippet")
                if not title_elem:
                    continue

                title = title_elem.get_text(strip=True)
                snippet = snippet_elem.get_text(strip=True) if snippet_elem else ""
                href = _clean_redirect_url(title_elem.get("href", ""))

                if href and title:
                    results.append({"title": title, "snippet": snippet, "url": href})

                if len(results) >= max_results:
                    break
        return results
    except Exception as e:
        logger.warning(f"DuckDuckGo search error for '{query}': {e}")
        return []


def search_web(query: str, max_results: int = 6) -> List[Dict[str, str]]:
    """Search live web with dual-engine fallback (Bing + DuckDuckGo)."""
    clean_query = query.strip()
    if not clean_query:
        return []

    # Try Bing first as primary resilient engine
    results = search_bing(clean_query, max_results=max_results)
    if not results:
        # Fallback to DuckDuckGo
        results = search_duckduckgo(clean_query, max_results=max_results)

    logger.info(f"Web search for '{clean_query}' returned {len(results)} results.")
    return results


def scrape_url(target_url: str, max_chars: int = 4000) -> Dict[str, Any]:
    """Fetch and extract clean, readable text from any web URL."""
    clean_url = target_url.strip()
    if not clean_url.startswith("http://") and not clean_url.startswith("https://"):
        clean_url = "https://" + clean_url

    try:
        req = urllib.request.Request(clean_url, headers=DEFAULT_HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            status_code = resp.status
            content_type = resp.headers.get("Content-Type", "")

            if "application/json" in content_type:
                data = resp.read().decode("utf-8", errors="ignore")
                return {
                    "url": clean_url,
                    "title": "JSON Data",
                    "status": status_code,
                    "content": data[:max_chars],
                }

            html = resp.read().decode("utf-8", errors="ignore")
            soup = BeautifulSoup(html, "html.parser")

            # Remove noise
            for elem in soup(["script", "style", "nav", "footer", "header", "noscript", "svg", "iframe", "form"]):
                elem.decompose()

            title = soup.title.string.strip() if soup.title and soup.title.string else clean_url

            # Extract main body text
            text = soup.get_text(separator=" ", strip=True)
            text = re.sub(r"\s+", " ", text).strip()

            return {
                "url": clean_url,
                "title": title,
                "status": status_code,
                "content": text[:max_chars],
            }

    except urllib.error.HTTPError as e:
        return {"url": clean_url, "title": "Error", "status": e.code, "error": f"HTTP {e.code}: {e.reason}"}
    except Exception as e:
        return {"url": clean_url, "title": "Error", "status": 500, "error": str(e)}


def _extract_price_and_availability(text: str) -> Dict[str, str]:
    """Analyze snippet or page text for price patterns and stock status."""
    price = "Call for Pricing / Not Listed"
    status = "Unknown"

    lower = text.lower()

    # Price regex e.g. $4,699.00 or $4699
    price_match = re.search(r"\$\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?)", text)
    if price_match:
        price = f"${price_match.group(1)}"

    # Stock indicators
    if any(k in lower for k in ["in stock", "available to ship", "ships today", "ready to ship", "add to cart", "buy now"]):
        status = "In Stock"
    elif any(k in lower for k in ["pre-order", "preorder", "reserve now", "coming soon", "announced"]):
        status = "Pre-Order / Announced"
    elif any(k in lower for k in ["out of stock", "sold out", "temporarily out of stock", "backorder"]):
        status = "Out of Stock / Backorder"
    elif any(k in lower for k in ["contact sales", "request quote", "call for price", "inquire", "custom quote"]):
        status = "Enterprise Quote Only"

    return {"price": price, "status": status}


def check_tech_resellers(product_name: str, target_resellers: Optional[List[str]] = None) -> Dict[str, Any]:
    """Scan top technology resellers and distributors for inventory, pricing, and stock status
    for a given product (e.g. 'Nvidia DGX Spark').
    """
    clean_product = product_name.strip()
    if not clean_product:
        return {"error": "Product name is required."}

    logger.info(f"Scanning tech resellers for '{clean_product}'...")

    findings = []
    resellers_to_check = TECH_RESELLERS
    if target_resellers:
        lower_targets = [r.lower() for r in target_resellers]
        resellers_to_check = [r for r in TECH_RESELLERS if any(t in r["name"].lower() or t in r["domain"] for t in lower_targets)]
        if not resellers_to_check:
            resellers_to_check = TECH_RESELLERS

    # 1. Target key stores specifically
    for reseller in resellers_to_check:
        query = f'"{clean_product}" site:{reseller["domain"]}'
        search_res = search_web(query, max_results=2)

        if not search_res:
            query = f'"{clean_product}" {reseller["name"]} in stock price'
            search_res = search_web(query, max_results=1)

        for item in search_res:
            clean_url = _clean_redirect_url(item["url"])
            parsed = _extract_price_and_availability(item["snippet"] + " " + item["title"])

            store_name = reseller["name"]
            domain_matched = urllib.parse.urlparse(clean_url).netloc
            for r in TECH_RESELLERS:
                if r["domain"] in domain_matched:
                    store_name = r["name"]
                    break

            findings.append({
                "reseller": store_name,
                "domain": domain_matched or reseller["domain"],
                "title": item["title"],
                "snippet": item["snippet"],
                "url": clean_url,
                "detected_price": parsed["price"],
                "detected_status": parsed["status"],
            })

    # 2. General Market Pricing Search
    market_query = f'"{clean_product}" price retailer buy in stock'
    market_results = search_web(market_query, max_results=4)
    for item in market_results:
        clean_url = _clean_redirect_url(item["url"])
        if any(f["url"] == clean_url for f in findings):
            continue
        parsed = _extract_price_and_availability(item["snippet"] + " " + item["title"])

        domain_matched = urllib.parse.urlparse(clean_url).netloc
        store_name = "Tech Outlet"
        for r in TECH_RESELLERS:
            if r["domain"] in domain_matched:
                store_name = r["name"]
                break

        findings.append({
            "reseller": store_name,
            "domain": domain_matched,
            "title": item["title"],
            "snippet": item["snippet"],
            "url": clean_url,
            "detected_price": parsed["price"],
            "detected_status": parsed["status"],
        })

    # Summarize findings
    in_stock_items = [f for f in findings if f["detected_status"] == "In Stock"]
    preorder_items = [f for f in findings if "Pre-Order" in f["detected_status"]]
    quoted_items = [f for f in findings if "Quote" in f["detected_status"]]

    overall_status = "In Stock" if in_stock_items else (
        "Pre-Order / Announced" if preorder_items else (
            "Enterprise Quote Only" if quoted_items else "Checking Retail Rollout"
        )
    )

    prices = [f["detected_price"] for f in findings if f["detected_price"] != "Call for Pricing / Not Listed"]

    return {
        "product": clean_product,
        "scanned_resellers": [r["name"] for r in resellers_to_check],
        "total_listings_found": len(findings),
        "overall_availability": overall_status,
        "detected_prices": list(set(prices)),
        "in_stock_count": len(in_stock_items),
        "listings": findings,
    }


def format_inventory_summary_for_chat(data: Dict[str, Any]) -> str:
    """Format the scraper output into an authentic, crisp summary for Chip."""
    product = data.get("product", "Hardware")
    overall = data.get("overall_availability", "Unknown")
    prices = data.get("detected_prices", [])
    listings = data.get("listings", [])

    price_str = ", ".join(prices) if prices else "Custom Enterprise Quote / Pricing pending"

    lines = [
        f"🔍 **Hardware Inventory Radar: {product}**",
        f"• **Market Status:** {overall}",
        f"• **Pricing Observed:** {price_str}",
        "",
        "**Retailer & Reseller Findings:**",
    ]

    if not listings:
        lines.append("No active retail listings detected yet across Newegg, CDW, or B&H.")
    else:
        for item in listings[:6]:
            store = item.get("reseller", "Retailer")
            title = item.get("title", "")
            price = item.get("detected_price", "Call for Price")
            status = item.get("detected_status", "Check Site")
            url = item.get("url", "")
            lines.append(f"- **{store}**: {title[:75]}...")
            lines.append(f"  Status: {status} | Price: {price}")
            if url:
                lines.append(f"  Link: {url}")
            lines.append("")

    return "\n".join(lines).strip()
