from fastapi import FastAPI, APIRouter, HTTPException
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict, Any
import uuid
from datetime import datetime, timedelta
from tavily import TavilyClient
from anthropic import AsyncAnthropic 
import re
import json
import urllib.parse

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

app = FastAPI()
api_router = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =================== URL OLUŞTURUCU MOTORU ===================

class LinkBuilder:
    def clean_url(self, url):
        return url.split('?')[0].split('#')[0]

    def generate_smart_link(self, raw_url, check_in, check_out, guest_count):
        if not raw_url: return "#"
        base_url = self.clean_url(raw_url)
        
        if not check_in or not check_out:
            return raw_url

        # ETS TUR
        if "etstur.com" in base_url:
            c_in = check_in.strftime("%d.%m.%Y")
            c_out = check_out.strftime("%d.%m.%Y")
            return f"{base_url}?check_in={c_in}&check_out={c_out}&adult_1={guest_count}&child_1=0"

        # ODAMAX
        elif "odamax.com" in base_url:
            c_in = check_in.strftime("%Y-%m-%d")
            c_out = check_out.strftime("%Y-%m-%d")
            return f"{base_url}?startDate={c_in}&endDate={c_out}&adults={guest_count}"

        # TATILBUDUR
        elif "tatilbudur.com" in base_url:
            c_in = check_in.strftime("%d.%m.%Y")
            c_out = check_out.strftime("%d.%m.%Y")
            return f"{base_url}?gidisTarihi={c_in}&donusTarihi={c_out}&yetiskinSayisi={guest_count}"
            
        # JOLLY TUR
        elif "jollytur.com" in base_url:
            c_in = check_in.strftime("%d.%m.%Y")
            c_out = check_out.strftime("%d.%m.%Y")
            return f"{base_url}?checkIn={c_in}&checkOut={c_out}&adult={guest_count}"
            
        # TATİL SEPETİ
        elif "tatilsepeti.com" in base_url:
            c_in = check_in.strftime("%Y-%m-%d")
            c_out = check_out.strftime("%Y-%m-%d")
            return f"{base_url}?gTarih={c_in}&dTarih={c_out}&kisi={guest_count}"

        # Bilinmeyen site ise dokunma
        return raw_url

# =================== MODELLER ===================

class ParsedFilters(BaseModel):
    city: Optional[str] = None
    district: Optional[str] = None
    guest_count: int = 2
    property_type: Optional[str] = None
    features: List[str] = []
    check_in_date: Optional[str] = None 
    check_out_date: Optional[str] = None
    raw_query: str = ""

class SearchRequest(BaseModel):
    filters: ParsedFilters

class ParseRequest(BaseModel):
    query: str

# =================== SERVISLER ===================

class AIService:
    def __init__(self):
        # Emergent key yerine Anthropic key kullanıyoruz
        self.client = AsyncAnthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))
    
    async def parse_query(self, query: str) -> ParsedFilters:
        try:
            system_msg = "Sen bir tatil asistanısın. Kullanıcı girdisinden JSON formatında filtreleri çıkar. Tarihleri YYYY-MM-DD formatında ver (yoksa null). Şehir, ilçe, kişi sayısı."
            message = await self.client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=1024,
                messages=[{"role": "user", "content": f"{system_msg}\nInput: {query}"}]
            )
            text = message.content[0].text
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            data = json.loads(json_match.group()) if json_match else {}
            return ParsedFilters(**data, raw_query=query)
        except:
            return ParsedFilters(raw_query=query)

class WebSearchService:
    def __init__(self):
        self.tavily = TavilyClient(api_key=os.environ.get('TAVILY_API_KEY'))
        self.linker = LinkBuilder()

    async def search(self, filters: ParsedFilters) -> List[Dict[str, Any]]:
        location = f"{filters.district} {filters.city}".strip()
        keywords = f"{filters.property_type or 'otel'} { ' '.join(filters.features[:2]) }"
        search_query = f"{location} {keywords} konaklama rezervasyon"
        
        try:
            response = self.tavily.search(
                query=search_query,
                search_depth="advanced",
                max_results=15,
                include_images=True
            )
        except:
            return []

        try:
            if filters.check_in_date:
                c_in = datetime.strptime(filters.check_in_date, "%Y-%m-%d")
            else:
                c_in = datetime.now() + timedelta(days=1)
            
            if filters.check_out_date:
                c_out = datetime.strptime(filters.check_out_date, "%Y-%m-%d")
            else:
                c_out = c_in + timedelta(days=5)
        except:
            c_in = datetime.now() + timedelta(days=1)
            c_out = c_in + timedelta(days=5)

        results = []
        seen_urls = set()

        for item in response.get('results', []):
            url = item.get('url')
            if url in seen_urls or url.count('/') < 4: continue
            seen_urls.add(url)

            image = item.get('image') or "https://images.unsplash.com/photo-1566073771259-6a8506099945?w=800&q=80"

            smart_url = self.linker.generate_smart_link(url, c_in, c_out, filters.guest_count or 2)
            
            domain = urllib.parse.urlparse(url).netloc.replace('www.', '')

            results.append({
                "id": str(uuid.uuid4()),
                "title": item.get('title', 'Konaklama Fırsatı'),
                "description": item.get('content', '')[:150] + "...",
                "price": "Fiyatı Gör",
                "image": image,
                "url": smart_url,
                "city": filters.city,
                "district": domain,
                "features": filters.features
            })

        return results

# =================== API ===================

ai_service = AIService()
web_search_service = WebSearchService()

@api_router.post("/parse")
async def parse(req: ParseRequest):
    return await ai_service.parse_query(req.query)

@api_router.post("/search")
async def search(req: SearchRequest):
    results = await web_search_service.search(req.filters)
    return {"results": results, "count": len(results), "source": "web"}

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)