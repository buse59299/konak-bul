from fastapi import FastAPI, APIRouter, HTTPException
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict, Any
import uuid
from datetime import datetime, timezone
from emergentintegrations.llm.chat import LlmChat, UserMessage
from tavily import TavilyClient
import googlemaps
import re
import json

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Create the main app without a prefix
app = FastAPI()

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# =================== MODELS ===================

class Accommodation(BaseModel):
    model_config = ConfigDict(extra="ignore")
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    description: str
    city: str
    district: Optional[str] = None
    property_type: str  # otel, villa, apart, bungalov, resort, butik otel, pansiyon
    price: Optional[str] = None
    features: List[str] = []  # havuzlu, denize sıfır, spa, jakuzi, şömine, WiFi
    image: Optional[str] = None
    url: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class ParseRequest(BaseModel):
    query: str

class ParsedFilters(BaseModel):
    city: Optional[str] = None
    district: Optional[str] = None
    price_min: Optional[int] = None
    price_max: Optional[int] = None
    guest_count: Optional[int] = None
    property_type: Optional[str] = None
    features: List[str] = []
    check_in_date: Optional[str] = None  # Format: "YYYY-MM-DD" or "DD MMM" like "2 Eylül"
    check_out_date: Optional[str] = None
    raw_query: str = ""

class SearchRequest(BaseModel):
    filters: ParsedFilters

class SearchResponse(BaseModel):
    results: List[Dict[str, Any]]
    count: int
    source: str  # "web" or "fallback"

class SuggestionsResponse(BaseModel):
    cities: List[str]
    features: List[str]
    property_types: List[str]

# =================== AI SERVICE ===================

class AIService:
    def __init__(self):
        # Use user's API key if available and valid, else use Emergent LLM key
        anthropic_key = os.environ.get('ANTHROPIC_API_KEY', '')
        
        # Check if it's a placeholder or empty
        if anthropic_key and anthropic_key != 'your-anthropic-api-key-here':
            api_key = anthropic_key
            logger.info("Using user's Anthropic API key")
        else:
            api_key = os.environ.get('EMERGENT_LLM_KEY')
            logger.info("Using Emergent LLM key")
        
        self.chat = LlmChat(
            api_key=api_key,
            session_id=f"parse-{uuid.uuid4()}",
            system_message="""Sen Türkiye'de konaklama arama konusunda uzman bir asistansın. 
            Kullanıcının Türkçe doğal dil sorgusunu analiz edip yapılandırılmış filtre verileri çıkar.
            
            Çıkarman gereken bilgiler:
            - city: şehir (örn: İstanbul, Antalya, Bodrum, Kapadokya)
            - district: ilçe/bölge (örn: Beşiktaş, Kaleiçi, Göreme)
            - price_min: minimum fiyat (TL)
            - price_max: maximum fiyat (TL)
            - guest_count: misafir sayısı
            - property_type: konaklama tipi (otel, villa, apart, bungalov, resort, butik otel, pansiyon)
            - features: özellikler listesi (havuzlu, denize sıfır, spa, jakuzi, şömine, WiFi, balkon, kahvaltı dahil)
            - check_in_date: giriş tarihi (örn: "2 Eylül", "15 Haziran", "2025-09-02")
            - check_out_date: çıkış tarihi (örn: "5 Eylül", "20 Haziran", "2025-09-05")
            
            TARİHLER ÖNEMLİ: Kullanıcı tarih belirtirse mutlaka çıkar!
            
            SADECE JSON formatında cevap ver, başka metin ekleme.
            Örnek:
            {
              "city": "Antalya",
              "district": null,
              "price_min": null,
              "price_max": null,
              "guest_count": 4,
              "property_type": "villa",
              "features": ["havuzlu", "denize sıfır"],
              "check_in_date": "2 Eylül",
              "check_out_date": "5 Eylül"
            }"""
        ).with_model("anthropic", "claude-4-sonnet-20250514")
    
    async def parse_query(self, query: str) -> ParsedFilters:
        try:
            logger.info(f"========== AI PARSE ==========")
            logger.info(f"Input Query: {query}")
            
            user_message = UserMessage(text=f"Parse this Turkish query: {query}")
            response = await self.chat.send_message(user_message)
            
            logger.info(f"AI Response: {response}")
            
            # Extract JSON from response - handle markdown code blocks
            json_text = response.strip()
            
            # Remove markdown code blocks if present
            if '```json' in json_text:
                json_text = re.search(r'```json\s*(\{.*?\})\s*```', json_text, re.DOTALL)
                if json_text:
                    json_text = json_text.group(1)
            elif '```' in json_text:
                json_text = re.search(r'```\s*(\{.*?\})\s*```', json_text, re.DOTALL)
                if json_text:
                    json_text = json_text.group(1)
            
            # Try to find JSON object
            json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', str(json_text), re.DOTALL)
            if json_match:
                parsed_data = json.loads(json_match.group())
            else:
                parsed_data = json.loads(json_text)
            
            logger.info(f"Parsed Data: {parsed_data}")
            
            filters = ParsedFilters(
                city=parsed_data.get('city'),
                district=parsed_data.get('district'),
                price_min=parsed_data.get('price_min'),
                price_max=parsed_data.get('price_max'),
                guest_count=parsed_data.get('guest_count'),
                property_type=parsed_data.get('property_type'),
                features=parsed_data.get('features', []),
                check_in_date=parsed_data.get('check_in_date'),
                check_out_date=parsed_data.get('check_out_date'),
                raw_query=query
            )
            
            logger.info(f"Filters Created: {filters.model_dump()}")
            logger.info(f"==============================")
            
            return filters
            
        except Exception as e:
            logger.error(f"AI parsing error: {str(e)}", exc_info=True)
            # Fallback to basic parsing with raw query
            logger.warning(f"Using fallback parsing for: {query}")
            return ParsedFilters(raw_query=query)

# =================== WEB SEARCH SERVICE ===================

class WebSearchService:
    def __init__(self):
        self.tavily_client = TavilyClient(api_key=os.environ.get('TAVILY_API_KEY'))
    
    async def search(self, filters: ParsedFilters) -> List[Dict[str, Any]]:
        try:
            # Build comprehensive search query from filters
            query_parts = []
            
            # Add location (city + district)
            if filters.city:
                query_parts.append(filters.city)
            if filters.district:
                query_parts.append(filters.district)
            
            # Add property type if specified
            if filters.property_type:
                query_parts.append(filters.property_type)
            
            # Add up to 2 key features
            if filters.features:
                query_parts.extend(filters.features[:2])
            
            # Add dates if specified
            if filters.check_in_date and filters.check_out_date:
                query_parts.append(f"{filters.check_in_date} - {filters.check_out_date}")
            elif filters.check_in_date:
                query_parts.append(filters.check_in_date)
            
            # Add guest count
            if filters.guest_count:
                query_parts.append(f"{filters.guest_count} kişi")
            
            # Add base keyword
            query_parts.append("konaklama Turkey")
            
            # Build final search query
            search_query = " ".join(query_parts)
            
            logger.info(f"========== TAVILY SEARCH ==========")
            logger.info(f"Parsed Filters: city={filters.city}, district={filters.district}, type={filters.property_type}, features={filters.features}")
            logger.info(f"Search Query: {search_query}")
            
            # Perform Tavily search WITHOUT domain restrictions to get more results
            response = self.tavily_client.search(
                query=search_query,
                search_depth="basic",
                max_results=15
            )
            
            logger.info(f"Tavily Raw Response: {response}")
            
            results = []
            if response and 'results' in response:
                logger.info(f"Tavily returned {len(response['results'])} total results")
                
                # Process ALL results from Tavily
                for idx, item in enumerate(response['results']):
                    title = item.get('title', '')
                    content = item.get('content', '')
                    url = item.get('url', '')
                    
                    logger.info(f"Result {idx}: Title='{title}', URL={url}")
                    
                    # More lenient filtering - accept any travel/accommodation related content
                    title_lower = title.lower()
                    content_lower = content.lower()
                    
                    # Check if it's accommodation related
                    keywords = ['hotel', 'otel', 'villa', 'apart', 'resort', 'konaklama', 
                                'tatil', 'booking', 'accommodation', 'stay', 'lodging',
                                'pension', 'pansiyon', 'bungalov', 'bungalow']
                    
                    is_accommodation = any(kw in title_lower or kw in content_lower for kw in keywords)
                    
                    if is_accommodation:
                        # Extract image if available
                        image_url = None
                        if 'image' in item and item['image']:
                            image_url = item['image']
                        
                        # Fallback images based on property type or city
                        if not image_url:
                            city_lower = (filters.city or '').lower()
                            prop_type = (filters.property_type or '').lower()
                            
                            if 'villa' in prop_type or 'villa' in title_lower:
                                image_url = 'https://images.unsplash.com/photo-1613490493576-7fde63acd811?w=800&q=80'
                            elif 'bungalov' in prop_type or 'bungalov' in title_lower:
                                image_url = 'https://images.unsplash.com/photo-1510798831971-661eb04b3739?w=800&q=80'
                            elif 'resort' in prop_type or 'resort' in title_lower:
                                image_url = 'https://images.unsplash.com/photo-1571896349842-33c89424de2d?w=800&q=80'
                            elif 'apart' in prop_type or 'apart' in title_lower:
                                image_url = 'https://images.unsplash.com/photo-1522708323590-d24dbb6b0267?w=800&q=80'
                            elif 'antalya' in city_lower or 'alanya' in city_lower:
                                image_url = 'https://images.unsplash.com/photo-1602002418082-a4443e081dd1?w=800&q=80'
                            elif 'bodrum' in city_lower:
                                image_url = 'https://images.unsplash.com/photo-1520250497591-112f2f40a3f4?w=800&q=80'
                            elif 'istanbul' in city_lower or 'İstanbul' in (filters.city or ''):
                                image_url = 'https://images.unsplash.com/photo-1541432901042-2d8bd64b4a9b?w=800&q=80'
                            else:
                                image_url = 'https://images.unsplash.com/photo-1566073771259-6a8506099945?w=800&q=80'
                        
                        # Try to extract price from content
                        price = None
                        import re
                        price_match = re.search(r'(\d+[.,]?\d*)\s*(TL|₺|USD|EUR)', content)
                        if price_match:
                            price = f"{price_match.group(1)} {price_match.group(2)}"
                        
                        result_item = {
                            'title': title,
                            'description': content[:250] if content else 'Konaklama detayları için tıklayın',
                            'url': url,
                            'image': image_url,
                            'price': price,
                            'city': filters.city or '',
                            'district': filters.district or '',
                            'features': filters.features if filters.features else []
                        }
                        
                        results.append(result_item)
                        logger.info(f"✓ Added result: {title}")
                    else:
                        logger.info(f"✗ Filtered out (not accommodation): {title}")
            
            logger.info(f"Final processed results count: {len(results)}")
            logger.info(f"===================================")
            
            return results
            
        except Exception as e:
            logger.error(f"Tavily search error: {str(e)}", exc_info=True)
            return []

# =================== FALLBACK DATA SERVICE ===================

class FallbackDataService:
    async def search(self, filters: ParsedFilters) -> List[Dict[str, Any]]:
        try:
            query = {}
            
            if filters.city:
                query['city'] = {'$regex': filters.city, '$options': 'i'}
            
            if filters.district:
                query['district'] = {'$regex': filters.district, '$options': 'i'}
            
            if filters.property_type:
                query['property_type'] = {'$regex': filters.property_type, '$options': 'i'}
            
            if filters.features:
                query['features'] = {'$in': filters.features}
            
            accommodations = await db.accommodations.find(query, {"_id": 0}).to_list(50)
            
            # Convert datetime to ISO string for serialization
            for acc in accommodations:
                if isinstance(acc.get('created_at'), str):
                    pass
                elif 'created_at' in acc:
                    acc['created_at'] = acc['created_at'].isoformat()
            
            logger.info(f"Fallback returned {len(accommodations)} results")
            return accommodations
            
        except Exception as e:
            logger.error(f"Fallback search error: {str(e)}")
            return []

# =================== API ENDPOINTS ===================

ai_service = AIService()
web_search_service = WebSearchService()
fallback_service = FallbackDataService()

@api_router.get("/")
async def root():
    return {"message": "AI Konaklama Asistanı API"}

@api_router.post("/parse", response_model=ParsedFilters)
async def parse_query(request: ParseRequest):
    """Parse Turkish natural language query into structured filters"""
    try:
        filters = await ai_service.parse_query(request.query)
        return filters
    except Exception as e:
        logger.error(f"Parse error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.post("/search", response_model=SearchResponse)
async def search_accommodations(request: SearchRequest):
    """Search accommodations using web search, fallback to local data"""
    try:
        filters = request.filters
        
        logger.info(f"========== SEARCH REQUEST ==========")
        logger.info(f"Filters: {filters.model_dump()}")
        
        # Try web search first
        web_results = await web_search_service.search(filters)
        
        logger.info(f"Web search returned {len(web_results)} results")
        
        # Only use web results if we actually got some
        if web_results and len(web_results) > 0:
            logger.info(f"✓ Using WEB results: {len(web_results)} items")
            return SearchResponse(
                results=web_results,
                count=len(web_results),
                source="web"
            )
        
        # Fallback to local data only if web search returned nothing
        logger.info("⚠ Web search returned 0 results, using FALLBACK data")
        fallback_results = await fallback_service.search(filters)
        
        logger.info(f"Fallback returned {len(fallback_results)} results")
        logger.info(f"====================================")
        
        return SearchResponse(
            results=fallback_results,
            count=len(fallback_results),
            source="fallback"
        )
        
    except Exception as e:
        logger.error(f"Search error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/suggestions", response_model=SuggestionsResponse)
async def get_suggestions():
    """Get autocomplete suggestions for cities and features"""
    return SuggestionsResponse(
        cities=[
            "İstanbul", "Antalya", "Bodrum", "Fethiye", "İzmir", 
            "Kapadokya", "Alaçatı", "Sapanca", "Çeşme", "Kuşadası",
            "Marmaris", "Alanya", "Side", "Belek", "Göcek"
        ],
        features=[
            "havuzlu", "denize sıfır", "spa", "jakuzi", "şömine",
            "WiFi", "balkon", "kahvaltı dahil", "klimalı", "otopark",
            "evcil hayvan kabul eder", "sauna", "fitness"
        ],
        property_types=[
            "otel", "villa", "apart", "bungalov", "resort", 
            "butik otel", "pansiyon", "dağ evi"
        ]
    )

@api_router.get("/accommodations", response_model=List[Accommodation])
async def get_all_accommodations():
    """Get all accommodations from fallback database"""
    try:
        accommodations = await db.accommodations.find({}, {"_id": 0}).to_list(100)
        
        # Convert datetime strings if needed
        for acc in accommodations:
            if isinstance(acc.get('created_at'), str):
                acc['created_at'] = datetime.fromisoformat(acc['created_at'])
        
        return accommodations
    except Exception as e:
        logger.error(f"Get accommodations error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_db():
    """Initialize database with fallback accommodation data"""
    try:
        # Check if data already exists
        count = await db.accommodations.count_documents({})
        if count > 0:
            logger.info(f"Database already has {count} accommodations")
            return
        
        # Create 50 sample Turkish accommodations
        sample_data = [
            # İstanbul
            {"title": "Pera Palace Hotel", "description": "Tarihi lüks otel, Beyoğlu'nun kalbinde", "city": "İstanbul", "district": "Beyoğlu", "property_type": "butik otel", "price": "3500 TL/gece", "features": ["WiFi", "kahvaltı dahil", "spa"], "image": "https://images.unsplash.com/photo-1566073771259-6a8506099945?w=800", "url": "#"},
            {"title": "Boğaz Manzaralı Villa", "description": "Özel havuzlu, 6 kişilik lüks villa", "city": "İstanbul", "district": "Beşiktaş", "property_type": "villa", "price": "8000 TL/gece", "features": ["havuzlu", "WiFi", "jakuzi", "balkon"], "image": "https://images.unsplash.com/photo-1613490493576-7fde63acd811?w=800", "url": "#"},
            {"title": "Modern Apart Daire", "description": "Şişli'de merkezi konumda apart", "city": "İstanbul", "district": "Şişli", "property_type": "apart", "price": "1500 TL/gece", "features": ["WiFi", "klimalı", "otopark"], "image": "https://images.unsplash.com/photo-1522708323590-d24dbb6b0267?w=800", "url": "#"},
            
            # Antalya
            {"title": "Denize Sıfır Resort", "description": "Her şey dahil lüks tatil köyü", "city": "Antalya", "district": "Lara", "property_type": "resort", "price": "4500 TL/gece", "features": ["denize sıfır", "havuzlu", "spa", "kahvaltı dahil"], "image": "https://images.unsplash.com/photo-1571896349842-33c89424de2d?w=800", "url": "#"},
            {"title": "Kaleiçi Butik Otel", "description": "Tarihi Kaleiçi'nde butik konaklama", "city": "Antalya", "district": "Kaleiçi", "property_type": "butik otel", "price": "2800 TL/gece", "features": ["WiFi", "kahvaltı dahil", "balkon"], "image": "https://images.unsplash.com/photo-1542314831-068cd1dbfeeb?w=800", "url": "#"},
            {"title": "Belek Golf Resort", "description": "Golf sahası manzaralı otel", "city": "Antalya", "district": "Belek", "property_type": "resort", "price": "5200 TL/gece", "features": ["havuzlu", "spa", "fitness", "kahvaltı dahil"], "image": "https://images.unsplash.com/photo-1564501049412-61c2a3083791?w=800", "url": "#"},
            {"title": "Konyaaltı Plaj Apart", "description": "Plaja 50m mesafede apart otel", "city": "Antalya", "district": "Konyaaltı", "property_type": "apart", "price": "1800 TL/gece", "features": ["denize sıfır", "WiFi", "balkon"], "image": "https://images.unsplash.com/photo-1512918728675-ed5a9ecdebfd?w=800", "url": "#"},
            {"title": "Side Antik Otel", "description": "Antik şehir manzaralı butik otel", "city": "Antalya", "district": "Side", "property_type": "butik otel", "price": "3200 TL/gece", "features": ["havuzlu", "WiFi", "kahvaltı dahil"], "image": "https://images.unsplash.com/photo-1551882547-ff40c63fe5fa?w=800", "url": "#"},
            
            # Bodrum
            {"title": "Bodrum Marina Otel", "description": "Marina manzaralı lüks konaklama", "city": "Bodrum", "district": "Merkez", "property_type": "otel", "price": "3800 TL/gece", "features": ["havuzlu", "WiFi", "spa", "balkon"], "image": "https://images.unsplash.com/photo-1520250497591-112f2f40a3f4?w=800", "url": "#"},
            {"title": "Yalıkavak Villa", "description": "Özel plajlı 8 kişilik villa", "city": "Bodrum", "district": "Yalıkavak", "property_type": "villa", "price": "12000 TL/gece", "features": ["havuzlu", "denize sıfır", "jakuzi", "WiFi"], "image": "https://images.unsplash.com/photo-1600596542815-ffad4c1539a9?w=800", "url": "#"},
            {"title": "Türkbükü Bungalov", "description": "Plaj kenarı romantik bungalov", "city": "Bodrum", "district": "Türkbükü", "property_type": "bungalov", "price": "4500 TL/gece", "features": ["denize sıfır", "balkon", "WiFi"], "image": "https://images.unsplash.com/photo-1510798831971-661eb04b3739?w=800", "url": "#"},
            {"title": "Gümbet Apart Otel", "description": "Aile dostu apart otel", "city": "Bodrum", "district": "Gümbet", "property_type": "apart", "price": "2200 TL/gece", "features": ["havuzlu", "WiFi", "klimalı"], "image": "https://images.unsplash.com/photo-1611892440504-42a792e24d32?w=800", "url": "#"},
            
            # Fethiye
            {"title": "Ölüdeniz Resort", "description": "Ölüdeniz manzaralı tatil köyü", "city": "Fethiye", "district": "Ölüdeniz", "property_type": "resort", "price": "3600 TL/gece", "features": ["denize sıfır", "havuzlu", "kahvaltı dahil", "spa"], "image": "https://images.unsplash.com/photo-1602002418082-a4443e081dd1?w=800", "url": "#"},
            {"title": "Göcek Marina Villa", "description": "Marina manzaralı lüks villa", "city": "Fethiye", "district": "Göcek", "property_type": "villa", "price": "9500 TL/gece", "features": ["havuzlu", "jakuzi", "WiFi", "balkon"], "image": "https://images.unsplash.com/photo-1613490493576-7fde63acd811?w=800", "url": "#"},
            {"title": "Çalış Plajı Apart", "description": "Plaj kenarı ekonomik apart", "city": "Fethiye", "district": "Çalış", "property_type": "apart", "price": "1600 TL/gece", "features": ["denize sıfır", "WiFi", "balkon"], "image": "https://images.unsplash.com/photo-1522708323590-d24dbb6b0267?w=800", "url": "#"},
            
            # Kapadokya
            {"title": "Mağara Otel", "description": "Otantik mağara otel, balon turu dahil", "city": "Kapadokya", "district": "Göreme", "property_type": "butik otel", "price": "2800 TL/gece", "features": ["WiFi", "kahvaltı dahil", "şömine"], "image": "https://images.unsplash.com/photo-1541480551145-2370a440d585?w=800", "url": "#"},
            {"title": "Ürgüp Kaya Evi", "description": "Tarihi taş ev, şömineli", "city": "Kapadokya", "district": "Ürgüp", "property_type": "butik otel", "price": "3200 TL/gece", "features": ["şömine", "WiFi", "kahvaltı dahil"], "image": "https://images.unsplash.com/photo-1563789031959-4c02bcb41319?w=800", "url": "#"},
            {"title": "Avanos Pansiyon", "description": "Aile işletmesi sıcak pansiyon", "city": "Kapadokya", "district": "Avanos", "property_type": "pansiyon", "price": "1200 TL/gece", "features": ["WiFi", "kahvaltı dahil"], "image": "https://images.unsplash.com/photo-1551882547-ff40c63fe5fa?w=800", "url": "#"},
            
            # İzmir
            {"title": "Kordon Otel", "description": "Kordon boyu deniz manzaralı", "city": "İzmir", "district": "Alsancak", "property_type": "otel", "price": "2400 TL/gece", "features": ["WiFi", "balkon", "kahvaltı dahil"], "image": "https://images.unsplash.com/photo-1566073771259-6a8506099945?w=800", "url": "#"},
            {"title": "Çeşme Marina Resort", "description": "Her şey dahil plaj oteli", "city": "İzmir", "district": "Çeşme", "property_type": "resort", "price": "4800 TL/gece", "features": ["denize sıfır", "havuzlu", "spa", "kahvaltı dahil"], "image": "https://images.unsplash.com/photo-1571896349842-33c89424de2d?w=800", "url": "#"},
            {"title": "Alaçatı Taş Ev", "description": "Restore edilmiş Rum evi", "city": "İzmir", "district": "Alaçatı", "property_type": "butik otel", "price": "3500 TL/gece", "features": ["WiFi", "kahvaltı dahil", "balkon"], "image": "https://images.unsplash.com/photo-1542314831-068cd1dbfeeb?w=800", "url": "#"},
            {"title": "Seferihisar Apart", "description": "Sakin kasaba merkezinde apart", "city": "İzmir", "district": "Seferihisar", "property_type": "apart", "price": "1400 TL/gece", "features": ["WiFi", "klimalı"], "image": "https://images.unsplash.com/photo-1522708323590-d24dbb6b0267?w=800", "url": "#"},
            
            # Sapanca
            {"title": "Göl Manzaralı Villa", "description": "Sapanca Gölü manzaralı şömineli villa", "city": "Sapanca", "property_type": "villa", "price": "5500 TL/gece", "features": ["şömine", "jakuzi", "WiFi", "balkon"], "image": "https://images.unsplash.com/photo-1600596542815-ffad4c1539a9?w=800", "url": "#"},
            {"title": "Ormaniçi Bungalov", "description": "Doğa içinde huzurlu bungalov", "city": "Sapanca", "property_type": "bungalov", "price": "3200 TL/gece", "features": ["şömine", "WiFi", "kahvaltı dahil"], "image": "https://images.unsplash.com/photo-1510798831971-661eb04b3739?w=800", "url": "#"},
            {"title": "Sapanca Dağ Evi", "description": "Kış ve yaz tatili için ideal", "city": "Sapanca", "property_type": "dağ evi", "price": "4000 TL/gece", "features": ["şömine", "jakuzi", "WiFi"], "image": "https://images.unsplash.com/photo-1613490493576-7fde63acd811?w=800", "url": "#"},
            
            # Marmaris
            {"title": "İçmeler Resort", "description": "Denize sıfır her şey dahil", "city": "Marmaris", "district": "İçmeler", "property_type": "resort", "price": "4200 TL/gece", "features": ["denize sıfır", "havuzlu", "spa", "kahvaltı dahil"], "image": "https://images.unsplash.com/photo-1571896349842-33c89424de2d?w=800", "url": "#"},
            {"title": "Marmaris Marina Otel", "description": "Marina ve kale manzaralı", "city": "Marmaris", "district": "Merkez", "property_type": "otel", "price": "3000 TL/gece", "features": ["havuzlu", "WiFi", "balkon"], "image": "https://images.unsplash.com/photo-1566073771259-6a8506099945?w=800", "url": "#"},
            {"title": "Turunç Butik Otel", "description": "Sakin koyda butik konaklama", "city": "Marmaris", "district": "Turunç", "property_type": "butik otel", "price": "2600 TL/gece", "features": ["denize sıfır", "WiFi", "kahvaltı dahil"], "image": "https://images.unsplash.com/photo-1542314831-068cd1dbfeeb?w=800", "url": "#"},
            
            # Alanya
            {"title": "Kleopatra Beach Hotel", "description": "Ünlü Kleopatra plajında", "city": "Alanya", "district": "Merkez", "property_type": "otel", "price": "2800 TL/gece", "features": ["denize sıfır", "havuzlu", "WiFi"], "image": "https://images.unsplash.com/photo-1520250497591-112f2f40a3f4?w=800", "url": "#"},
            {"title": "Alanya Castle View", "description": "Kale manzaralı apart otel", "city": "Alanya", "district": "Kaleiçi", "property_type": "apart", "price": "1900 TL/gece", "features": ["WiFi", "balkon", "klimalı"], "image": "https://images.unsplash.com/photo-1522708323590-d24dbb6b0267?w=800", "url": "#"},
            {"title": "Konakli Resort", "description": "Aile dostu her şey dahil", "city": "Alanya", "district": "Konaklı", "property_type": "resort", "price": "3800 TL/gece", "features": ["denize sıfır", "havuzlu", "kahvaltı dahil", "spa"], "image": "https://images.unsplash.com/photo-1571896349842-33c89424de2d?w=800", "url": "#"},
            
            # Kuşadası
            {"title": "Ladies Beach Resort", "description": "Kadınlar Denizi kenarında", "city": "Kuşadası", "district": "Merkez", "property_type": "resort", "price": "3400 TL/gece", "features": ["denize sıfır", "havuzlu", "spa", "WiFi"], "image": "https://images.unsplash.com/photo-1571896349842-33c89424de2d?w=800", "url": "#"},
            {"title": "Kuşadası Marina Apart", "description": "Marina manzaralı modern apart", "city": "Kuşadası", "property_type": "apart", "price": "2000 TL/gece", "features": ["WiFi", "balkon", "klimalı"], "image": "https://images.unsplash.com/photo-1611892440504-42a792e24d32?w=800", "url": "#"},
            {"title": "Davutlar Villa", "description": "Milli park kenarı özel villa", "city": "Kuşadası", "district": "Davutlar", "property_type": "villa", "price": "6500 TL/gece", "features": ["havuzlu", "jakuzi", "WiFi"], "image": "https://images.unsplash.com/photo-1600596542815-ffad4c1539a9?w=800", "url": "#"},
            
            # Additional cities
            {"title": "Abant Göl Evi", "description": "Göl kenarı romantik konaklama", "city": "Bolu", "district": "Abant", "property_type": "dağ evi", "price": "3800 TL/gece", "features": ["şömine", "WiFi", "kahvaltı dahil"], "image": "https://images.unsplash.com/photo-1510798831971-661eb04b3739?w=800", "url": "#"},
            {"title": "Uludağ Kayak Oteli", "description": "Pistlere yakın kayak oteli", "city": "Bursa", "district": "Uludağ", "property_type": "otel", "price": "4500 TL/gece", "features": ["şömine", "spa", "WiFi", "kahvaltı dahil"], "image": "https://images.unsplash.com/photo-1520250497591-112f2f40a3f4?w=800", "url": "#"},
            {"title": "Mudanya Sahil Apart", "description": "Deniz kenarı ekonomik konaklama", "city": "Bursa", "district": "Mudanya", "property_type": "apart", "price": "1300 TL/gece", "features": ["denize sıfır", "WiFi"], "image": "https://images.unsplash.com/photo-1522708323590-d24dbb6b0267?w=800", "url": "#"},
            {"title": "Pamukkale Termal Otel", "description": "Termal havuzlu spa otel", "city": "Denizli", "district": "Pamukkale", "property_type": "otel", "price": "3000 TL/gece", "features": ["spa", "havuzlu", "WiFi", "kahvaltı dahil"], "image": "https://images.unsplash.com/photo-1566073771259-6a8506099945?w=800", "url": "#"},
            {"title": "Trabzon Uzungöl Evi", "description": "Uzungöl manzaralı dağ evi", "city": "Trabzon", "district": "Uzungöl", "property_type": "dağ evi", "price": "2800 TL/gece", "features": ["şömine", "WiFi", "kahvaltı dahil"], "image": "https://images.unsplash.com/photo-1613490493576-7fde63acd811?w=800", "url": "#"},
            {"title": "Ayvalık Taş Otel", "description": "Tarihi Rum evinde butik otel", "city": "Balıkesir", "district": "Ayvalık", "property_type": "butik otel", "price": "2600 TL/gece", "features": ["WiFi", "kahvaltı dahil", "balkon"], "image": "https://images.unsplash.com/photo-1542314831-068cd1dbfeeb?w=800", "url": "#"},
            {"title": "Edremit Körfez Villa", "description": "Akdeniz manzaralı özel villa", "city": "Balıkesir", "district": "Edremit", "property_type": "villa", "price": "7000 TL/gece", "features": ["havuzlu", "denize sıfır", "WiFi", "jakuzi"], "image": "https://images.unsplash.com/photo-1600596542815-ffad4c1539a9?w=800", "url": "#"},
            {"title": "Datça Butik Pansiyon", "description": "Sakin kasabada aile pansiyonu", "city": "Muğla", "district": "Datça", "property_type": "pansiyon", "price": "1800 TL/gece", "features": ["WiFi", "kahvaltı dahil"], "image": "https://images.unsplash.com/photo-1551882547-ff40c63fe5fa?w=800", "url": "#"},
            {"title": "Akyaka Kitesurf Apart", "description": "Sörf tutkunları için ideal", "city": "Muğla", "district": "Akyaka", "property_type": "apart", "price": "2200 TL/gece", "features": ["denize sıfır", "WiFi", "balkon"], "image": "https://images.unsplash.com/photo-1522708323590-d24dbb6b0267?w=800", "url": "#"},
            {"title": "Kaş Deniz Manzaralı Otel", "description": "Likya yolu başlangıcında", "city": "Antalya", "district": "Kaş", "property_type": "butik otel", "price": "3400 TL/gece", "features": ["denize sıfır", "WiFi", "kahvaltı dahil", "balkon"], "image": "https://images.unsplash.com/photo-1542314831-068cd1dbfeeb?w=800", "url": "#"},
            {"title": "Olympos Ağaç Evleri", "description": "Doğa içinde ağaç ev konsepti", "city": "Antalya", "district": "Olympos", "property_type": "bungalov", "price": "2400 TL/gece", "features": ["WiFi", "kahvaltı dahil"], "image": "https://images.unsplash.com/photo-1510798831971-661eb04b3739?w=800", "url": "#"},
            {"title": "Cirali Sahil Pansiyon", "description": "Caretta plajı kenarında", "city": "Antalya", "district": "Çıralı", "property_type": "pansiyon", "price": "1600 TL/gece", "features": ["denize sıfır", "WiFi", "kahvaltı dahil"], "image": "https://images.unsplash.com/photo-1551882547-ff40c63fe5fa?w=800", "url": "#"},
            {"title": "Şirince Köy Evi", "description": "Tarihi köyde restore edilmiş ev", "city": "İzmir", "district": "Şirince", "property_type": "butik otel", "price": "2300 TL/gece", "features": ["WiFi", "kahvaltı dahil"], "image": "https://images.unsplash.com/photo-1542314831-068cd1dbfeeb?w=800", "url": "#"},
            {"title": "Foça Marina Otel", "description": "Marina ve adalar manzaralı", "city": "İzmir", "district": "Foça", "property_type": "otel", "price": "2800 TL/gece", "features": ["denize sıfır", "havuzlu", "WiFi"], "image": "https://images.unsplash.com/photo-1520250497591-112f2f40a3f4?w=800", "url": "#"},
            {"title": "Bozcaada Bağ Evi", "description": "Üzüm bağları arasında taş ev", "city": "Çanakkale", "district": "Bozcaada", "property_type": "butik otel", "price": "3200 TL/gece", "features": ["WiFi", "kahvaltı dahil", "balkon"], "image": "https://images.unsplash.com/photo-1563789031959-4c02bcb41319?w=800", "url": "#"},
            {"title": "Assos Antik Liman", "description": "Antik liman manzaralı pansiyon", "city": "Çanakkale", "district": "Assos", "property_type": "pansiyon", "price": "2000 TL/gece", "features": ["WiFi", "kahvaltı dahil", "balkon"], "image": "https://images.unsplash.com/photo-1551882547-ff40c63fe5fa?w=800", "url": "#"},
            {"title": "Gökçeada Rüzgar Evi", "description": "Ada'nın en sakin köşesinde", "city": "Çanakkale", "district": "Gökçeada", "property_type": "apart", "price": "2400 TL/gece", "features": ["WiFi", "balkon"], "image": "https://images.unsplash.com/photo-1522708323590-d24dbb6b0267?w=800", "url": "#"},
        ]
        
        # Insert accommodations
        for acc_data in sample_data:
            acc_data['id'] = str(uuid.uuid4())
            acc_data['created_at'] = datetime.now(timezone.utc).isoformat()
            await db.accommodations.insert_one(acc_data)
        
        logger.info(f"Successfully inserted {len(sample_data)} accommodations")
        
    except Exception as e:
        logger.error(f"Startup error: {str(e)}")

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()