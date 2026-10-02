"""
Web Service for Sarahzine 800 (ChipAI)
Provides resilient live web search, deep page scraping, and real-time inventory
and price tracking across:
- Secondary marketplaces: eBay, Mercari, Poshmark, Vinted, Grailed, Depop, Etsy
- Tech resellers & distributors: Newegg, CDW, B&H Photo, Micro Center, Insight, Provantage, Connection, NVIDIA
- General e-commerce & brand official stores
"""

import os
import re
import base64
import json
import logging
import urllib.parse
import urllib.request
import urllib.error
import html
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
    {"name": "Newegg", "domain": "newegg.com"},
    {"name": "CDW", "domain": "cdw.com"},
    {"name": "B&H Photo Video", "domain": "bhphotovideo.com"},
    {"name": "Micro Center", "domain": "microcenter.com"},
    {"name": "Insight", "domain": "insight.com"},
    {"name": "Provantage", "domain": "provantage.com"},
    {"name": "Connection", "domain": "connection.com"},
    {"name": "NVIDIA Direct", "domain": "nvidia.com"},
]

MARKETPLACES = [
    {"name": "eBay", "domain": "ebay.com"},
    {"name": "Mercari", "domain": "mercari.com"},
    {"name": "Poshmark", "domain": "poshmark.com"},
    {"name": "Vinted", "domain": "vinted.com"},
    {"name": "Grailed", "domain": "grailed.com"},
    {"name": "Depop", "domain": "depop.com"},
    {"name": "Etsy", "domain": "etsy.com"},
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

    if "uddg=" in raw_url:
        try:
            parsed = urllib.parse.parse_qs(urllib.parse.urlparse(raw_url).query)
            if "uddg" in parsed:
                return parsed["uddg"][0]
        except Exception:
            pass

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


def search_ddgs(query: str, max_results: int = 6) -> List[Dict[str, str]]:
    """Search via ddgs engine."""
    results = []
    try:
        from ddgs import DDGS
        d = DDGS(timeout=10)
        raw_items = list(d.text(query, max_results=max_results))
        for r in raw_items:
            title = r.get("title", "")
            snippet = r.get("body", "")
            href = r.get("href", "")
            clean_href = _clean_redirect_url(href)
            if title and clean_href:
                results.append({"title": title, "snippet": snippet, "url": clean_href})
    except Exception as e:
        logger.warning(f"ddgs search error for '{query}': {e}")
    return results


def search_bing(query: str, max_results: int = 6) -> List[Dict[str, str]]:
    """Search via Bing and unwrap direct URLs."""
    url = f"https://www.bing.com/search?q={urllib.parse.quote(query)}"
    results = []
    try:
        req = urllib.request.Request(url, headers=DEFAULT_HEADERS)
        with urllib.request.urlopen(req, timeout=12) as resp:
            html_text = resp.read().decode("utf-8", errors="ignore")
            soup = BeautifulSoup(html_text, "html.parser")

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
            html_text = resp.read().decode("utf-8", errors="ignore")
            soup = BeautifulSoup(html_text, "html.parser")

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
    """Search live web across multiple engines with automatic fallbacks."""
    clean_query = query.strip()
    if not clean_query:
        return []

    # 1. Try ddgs
    results = search_ddgs(clean_query, max_results=max_results)

    # 2. Try Bing if empty
    if not results:
        results = search_bing(clean_query, max_results=max_results)

    # 3. Try DDG HTML if still empty
    if not results:
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

            html_text = resp.read().decode("utf-8", errors="ignore")
            soup = BeautifulSoup(html_text, "html.parser")

            for elem in soup(["script", "style", "nav", "footer", "header", "noscript", "svg", "iframe", "form"]):
                elem.decompose()

            title = soup.title.string.strip() if soup.title and soup.title.string else clean_url
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
    price = "Check Listing / Inquire"
    status = "Available / Listed"

    lower = text.lower()

    # Price regex e.g. $4,699.00 or $4699 or $95
    price_match = re.search(r"\$\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?)", text)
    if not price_match:
        price_match = re.search(r"\$\s*([0-9]+)", text)

    if price_match:
        price = f"${price_match.group(1)}"

    # Stock indicators
    if any(k in lower for k in ["sold out", "item sold", "out of stock", "no longer available"]):
        status = "Sold Out"
    elif any(k in lower for k in ["in stock", "available to ship", "ships today", "ready to ship", "add to cart", "buy now"]):
        status = "In Stock"
    elif any(k in lower for k in ["pre-order", "preorder", "reserve now", "coming soon", "announced"]):
        status = "Pre-Order / Announced"
    elif any(k in lower for k in ["contact sales", "request quote", "call for price", "inquire", "custom quote"]):
        status = "Enterprise Quote Only"

    return {"price": price, "status": status}


def _is_relevant_match(product_name: str, item_title: str) -> bool:
    """Ensure the scraped listing title actually pertains to the requested product."""
    if not item_title:
        return False
    prod_lower = product_name.lower().strip()
    title_lower = item_title.lower().strip()

    # Hardware check: DGX Spark
    if "dgx" in prod_lower or "spark" in prod_lower:
        return ("dgx" in title_lower and "spark" in title_lower) or "dgx spark" in title_lower

    # Honey Badger / Goorin Bros check
    if "honey badger" in prod_lower or "badger" in prod_lower:
        return "badger" in title_lower or "nasty" in title_lower

    # General product tokens check: at least 50% of significant tokens must appear in title
    tokens = [t for t in re.findall(r"\b[a-zA-Z0-9]{3,}\b", prod_lower) if t not in ["the", "for", "and", "with"]]
    if not tokens:
        return True
    matches = sum(1 for t in tokens if t in title_lower)
    return (matches / len(tokens)) >= 0.5


def search_poshmark_direct(query: str, max_results: int = 6) -> List[Dict[str, Any]]:
    """Directly scrape Poshmark listings for an item."""
    listings = []
    try:
        import primp
        client = primp.Client(impersonate="random")
        p_url = f"https://poshmark.com/search?query={urllib.parse.quote(query)}"
        r = client.get(p_url, timeout=10)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.find_all("a"):
                href = a.get("href", "")
                text = a.get_text(separator=" ", strip=True)
                if "/listing/" in href and text and len(text) > 8:
                    full_url = "https://poshmark.com" + href if href.startswith("/") else href
                    price_match = re.search(r"\$\s*([0-9]+(?:\.[0-9]{2})?)", text)
                    price = f"${price_match.group(1)}" if price_match else "See Listing"
                    clean_title = re.sub(r"\$\s*[0-9]+.*$", "", text).strip()
                    if not clean_title:
                        clean_title = text

                    if _is_relevant_match(query, clean_title) and not any(l["url"] == full_url for l in listings):
                        listings.append({
                            "reseller": "Poshmark",
                            "domain": "poshmark.com",
                            "title": clean_title[:100],
                            "snippet": text[:150],
                            "url": full_url,
                            "detected_price": price,
                            "detected_status": "In Stock / Listed",
                        })
                    if len(listings) >= max_results:
                        break
    except Exception as e:
        logger.warning(f"Poshmark direct scrape error: {e}")
    return listings


def check_product_inventory(product_name: str, target_resellers: Optional[Any] = None) -> Dict[str, Any]:
    """Universal product radar scanner.
    Scans secondary marketplaces (eBay, Mercari, Poshmark, Vinted, Grailed, Depop, Etsy)
    AND tech resellers (Newegg, CDW, Micro Center, B&H, NVIDIA, Insight)
    AND brand/retail stores for stock, pricing, and active listings.
    """
    clean_product = product_name.strip()
    if not clean_product:
        return {"error": "Product name is required."}

    logger.info(f"Scanning inventory radar for '{clean_product}'...")

    findings: List[Dict[str, Any]] = []

    # Parse target platforms if supplied
    targets: List[str] = []
    if isinstance(target_resellers, list):
        targets = [str(t).lower() for t in target_resellers]
    elif isinstance(target_resellers, str) and target_resellers.lower() not in ["all", "none", ""]:
        targets = [t.strip().lower() for t in target_resellers.split(",")]

    tech_keywords = ["nvidia", "dgx", "spark", "gpu", "rtx", "geforce", "server", "intel", "amd", "workstation", "supercomputer"]
    is_tech_product = any(k in clean_product.lower() for k in tech_keywords)

    marketplace_keywords = ["ebay", "mercari", "poshmark", "vinted", "grailed", "depop", "etsy"]
    apparel_collectibles_keywords = [
        "hat", "cap", "shirt", "shoe", "sneaker", "hoodie", "jacket",
        "vintage", "card", "collectible", "badger", "goorin", "gorham", "pants", "dress", "tee"
    ]

    is_marketplace_target = any(any(m in t for m in marketplace_keywords) for t in targets)
    is_apparel_collectible = any(w in clean_product.lower() for w in apparel_collectibles_keywords)

    # Only search fashion/streetwear marketplaces if:
    # 1. Item is apparel/collectible, OR
    # 2. Marketplaces are explicitly in target platforms, OR
    # 3. Item is NOT an enterprise tech server/GPU
    wants_marketplaces = is_marketplace_target or is_apparel_collectible or (not is_tech_product and not targets)
    wants_tech = is_tech_product or any(any(t_name in t for t_name in ["newegg", "cdw", "microcenter", "nvidia", "bh", "insight"]) for t in targets) or (not is_apparel_collectible and not targets)

    # 1. Poshmark direct search
    if wants_marketplaces:
        posh_results = search_poshmark_direct(clean_product, max_results=5)
        for pr in posh_results:
            if _is_relevant_match(clean_product, pr["title"]):
                findings.append(pr)

    # 2. Marketplace queries via ddgs (eBay, Mercari, Vinted)
    if wants_marketplaces:
        queries_to_run = [
            f'"{clean_product}" ebay',
            f'"{clean_product}" mercari',
            f'"{clean_product}" vinted',
        ]
        for q in queries_to_run:
            ddgs_res = search_ddgs(q, max_results=3)
            for item in ddgs_res:
                href = item["url"]
                if not _is_relevant_match(clean_product, item["title"]):
                    continue
                if any(f["url"] == href for f in findings):
                    continue

                domain = urllib.parse.urlparse(href).netloc
                reseller_name = "Web Listing"
                for m in MARKETPLACES:
                    if m["domain"] in domain:
                        reseller_name = m["name"]
                        break
                if "goorin.com" in domain:
                    reseller_name = "Goorin Bros Direct"

                parsed = _extract_price_and_availability(item["title"] + " " + item["snippet"])

                findings.append({
                    "reseller": reseller_name,
                    "domain": domain,
                    "title": item["title"],
                    "snippet": item["snippet"],
                    "url": href,
                    "detected_price": parsed["price"],
                    "detected_status": parsed["status"],
                })

    # 3. Tech Resellers check (Newegg, CDW, Micro Center, B&H, NVIDIA, Insight, Provantage, Connection)
    if wants_tech:
        resellers_to_check = TECH_RESELLERS
        if targets:
            filtered = [r for r in TECH_RESELLERS if any(t in r["name"].lower() or t in r["domain"] for t in targets)]
            if filtered:
                resellers_to_check = filtered

        for reseller in resellers_to_check:
            query = f'"{clean_product}" site:{reseller["domain"]}'
            search_res = search_web(query, max_results=2)
            if not search_res:
                query = f'"{clean_product}" {reseller["name"]} in stock price'
                search_res = search_web(query, max_results=1)

            for item in search_res:
                if not _is_relevant_match(clean_product, item["title"]):
                    continue

                clean_url = _clean_redirect_url(item["url"])
                if any(f["url"] == clean_url for f in findings):
                    continue
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

    # 4. General fallback search if no specific listings found yet
    if not findings:
        general_results = search_web(f'"{clean_product}" price in stock buy', max_results=4)
        for item in general_results:
            if not _is_relevant_match(clean_product, item["title"]):
                continue
            clean_url = _clean_redirect_url(item["url"])
            if any(f["url"] == clean_url for f in findings):
                continue
            parsed = _extract_price_and_availability(item["snippet"] + " " + item["title"])
            domain_matched = urllib.parse.urlparse(clean_url).netloc
            findings.append({
                "reseller": domain_matched.replace("www.", "") if domain_matched else "Online Store",
                "domain": domain_matched,
                "title": item["title"],
                "snippet": item["snippet"],
                "url": clean_url,
                "detected_price": parsed["price"],
                "detected_status": parsed["status"],
            })

    # Summarize findings
    in_stock_items = [f for f in findings if f["detected_status"] in ["In Stock", "In Stock / Listed", "Available / Listed"]]
    preorder_items = [f for f in findings if "Pre-Order" in f["detected_status"]]
    quoted_items = [f for f in findings if "Quote" in f["detected_status"] or "Check Listing" in f.get("detected_price", "")]

    # If it's a pre-launch or enterprise hardware, don't claim in stock unless an explicit cart checkout is found
    if is_tech_product:
        # Check if any retailer has an actual cart checkout price
        has_real_retail_price = any(
            f["detected_price"] not in ["Check Listing / Inquire", "Call for Pricing / Not Listed", "See Listing"]
            for f in findings
        )
        if not has_real_retail_price:
            overall_status = "Enterprise Quote / Pre-Order Only (No Retail Cart Checkout)"
        elif in_stock_items:
            overall_status = "In Stock / Available"
        elif preorder_items:
            overall_status = "Pre-Order / Announced"
        else:
            overall_status = "Enterprise Quote / Pre-Order Only"
    else:
        overall_status = "In Stock / Available" if in_stock_items else (
            "Pre-Order / Announced" if preorder_items else (
                "Enterprise Quote Only" if quoted_items else "Checking Availability"
            )
        )

    prices = [
        f["detected_price"] for f in findings
        if f["detected_price"] not in ["Check Listing / Inquire", "Call for Pricing / Not Listed", "See Listing"]
    ]

    return {
        "product": clean_product,
        "total_listings_found": len(findings),
        "overall_availability": overall_status,
        "detected_prices": list(set(prices)),
        "in_stock_count": len(in_stock_items),
        "listings": findings,
    }


# Backwards compatibility alias
check_tech_resellers = check_product_inventory


def format_inventory_summary_for_chat(data: Dict[str, Any]) -> str:
    """Format the scraper output into an authentic, crisp summary for Chip."""
    product = data.get("product", "Item")
    overall = data.get("overall_availability", "Unknown")
    prices = data.get("detected_prices", [])
    listings = data.get("listings", [])

    price_str = ", ".join(prices) if prices else "Check individual listing"

    lines = [
        f"🔍 **Inventory Radar: {product}**",
        f"• **Market Status:** {overall}",
        f"• **Pricing Observed:** {price_str}",
        "",
        "**Active Listings Found:**",
    ]

    if not listings:
        lines.append("No active listings detected right now across monitored platforms.")
    else:
        for item in listings[:6]:
            store = item.get("reseller", "Store")
            title = item.get("title", "")
            price = item.get("detected_price", "Check site")
            status = item.get("detected_status", "Active")
            url = item.get("url", "")
            lines.append(f"- **{store}**: {title[:80]}")
            lines.append(f"  Status: {status} | Price: {price}")
            if url:
                lines.append(f"  Link: {url}")
            lines.append("")

    return "\n".join(lines).strip()
