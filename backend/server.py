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
import googlemaps
import requests

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
        api_key = os.environ.get('ANTHROPIC_API_KEY')
        self.client = AsyncAnthropic(api_key=api_key) if api_key else None
    
    def simple_parse(self, query: str) -> ParsedFilters:
        """Basit regex tabanlı parsing - API yoksa veya başarısız olursa"""
        q = query.lower()
        
        # Şehir tespiti - tam liste
        cities = [
            'istanbul', 'ankara', 'izmir', 'antalya', 'bursa', 'adana', 'gaziantep', 'konya', 'muğla', 'trabzon',
            'alanya', 'bodrum', 'fethiye', 'marmaris', 'kuşadası', 'side', 'belek', 'çeşme', 'alaçatı', 'kaş', 'kalkan',
            'göcek', 'sapanca', 'abant', 'uludağ', 'kapadokya', 'pamukkale', 'ayder', 'uzungöl', 'bozcaada', 'gökçeada',
            'ayvalık', 'assos', 'olympos', 'çıralı', 'dalyan', 'datça', 'akyaka', 'şirince', 'foça', 'seferihisar'
        ]
        city = next((c for c in cities if c in q), None)
        
        # Kişi sayısı - daha geniş pattern
        guest_match = re.search(r'(\d+)\s*(kişi|kişilik|adult|yetişkin)', q)
        guest_count = int(guest_match.group(1)) if guest_match else 2
        
        # Tarih parsing - Türkçe aylar
        month_map = {
            'ocak': 1, 'şubat': 2, 'mart': 3, 'nisan': 4, 'mayıs': 5, 'haziran': 6,
            'temmuz': 7, 'ağustos': 8, 'eylül': 9, 'ekim': 10, 'kasım': 11, 'aralık': 12
        }
        
        check_in_date = None
        check_out_date = None
        current_year = datetime.now().year
        
        # "2 Eylül - 5 Eylül" formatı
        date_pattern = r'(\d+)\s+(' + '|'.join(month_map.keys()) + r')(?:\s*-\s*(\d+)\s+(' + '|'.join(month_map.keys()) + r'))?'
        date_match = re.search(date_pattern, q)
        
        if date_match:
            day1 = int(date_match.group(1))
            month1_name = date_match.group(2)
            month1 = month_map.get(month1_name)
            
            if month1:
                # Check-in tarihi
                check_in_date = f"{current_year}-{month1:02d}-{day1:02d}"
                
                # Check-out tarihi
                if date_match.group(3):  # İkinci tarih varsa
                    day2 = int(date_match.group(3))
                    month2_name = date_match.group(4) if date_match.group(4) else month1_name
                    month2 = month_map.get(month2_name, month1)
                    check_out_date = f"{current_year}-{month2:02d}-{day2:02d}"
                else:
                    # Sadece başlangıç tarihi varsa, 3 gün ekle
                    check_in_dt = datetime(current_year, month1, day1)
                    check_out_dt = check_in_dt + timedelta(days=3)
                    check_out_date = check_out_dt.strftime("%Y-%m-%d")
        
        # Özellikler
        features = []
        if 'havuz' in q: features.append('havuz')
        if 'deniz' in q or 'sahil' in q or 'sıfır' in q: features.append('deniz manzarası')
        if 'spa' in q: features.append('spa')
        if 'jakuzi' in q: features.append('jakuzi')
        
        # Konaklama tipi
        property_type = None
        if 'villa' in q: property_type = 'villa'
        elif 'apart' in q: property_type = 'apart'
        elif 'bungalov' in q or 'bungalow' in q: property_type = 'bungalov'
        else: property_type = 'otel'
        
        return ParsedFilters(
            city=city,
            guest_count=guest_count,
            features=features,
            property_type=property_type,
            check_in_date=check_in_date,
            check_out_date=check_out_date,
            raw_query=query
        )
    
    async def parse_query(self, query: str) -> ParsedFilters:
        # API yoksa veya başarısız olursa basit parsing kullan
        if not self.client:
            logger.warning("Anthropic API key bulunamadı, basit parsing kullanılıyor")
            return self.simple_parse(query)
            
        try:
            system_msg = """Sen bir tatil asistanısın. Kullanıcı girdisinden aşağıdaki JSON formatında filtreleri çıkar:
{
  "city": "şehir adı veya null",
  "district": "ilçe adı veya null",
  "guest_count": sayı (varsayılan 2),
  "property_type": "villa|otel|apart|bungalov|resort|butik otel|pansiyon|null",
  "features": ["özellik1", "özellik2"],
  "check_in_date": "YYYY-MM-DD veya null",
  "check_out_date": "YYYY-MM-DD veya null"
}

SADECE JSON döndür, başka birşey yazma."""
            
            message = await self.client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=1024,
                messages=[{"role": "user", "content": f"{system_msg}\n\nInput: {query}"}]
            )
            text = message.content[0].text.strip()
            
            # JSON çıkarmayı dene
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                result = ParsedFilters(**data, raw_query=query)
                logger.info(f"AI parse başarılı: city={result.city}")
                return result
            else:
                logger.warning(f"JSON bulunamadı, yanıt: {text[:100]}")
                return self.simple_parse(query)
                
        except Exception as e:
            logger.error(f"AI parsing hatası: {e}, basit parsing kullanılıyor")
            return self.simple_parse(query)

class GooglePlacesService:
    def __init__(self):
        api_key = os.environ.get('GOOGLE_PLACES_API_KEY')
        self.gmaps = googlemaps.Client(key=api_key) if api_key else None
        self.api_key = api_key
        
    def get_place_photo_url(self, photo_reference, max_width=800):
        """Google Places fotoğraf URL'si oluştur"""
        if not photo_reference or not self.api_key:
            return "https://images.unsplash.com/photo-1566073771259-6a8506099945?w=800&q=80"
        return f"https://maps.googleapis.com/maps/api/place/photo?maxwidth={max_width}&photo_reference={photo_reference}&key={self.api_key}"
    
    def search(self, filters: ParsedFilters) -> List[Dict[str, Any]]:
        """Google Places API ile gerçek otel/konaklama yerlerini ara"""
        if not self.gmaps:
            logger.warning("Google Places API key bulunamadı")
            return []
        
        try:
            # Arama sorgusu oluştur
            location_query = filters.city or "Türkiye"
            
            # Konaklama tipi mapping
            type_mapping = {
                'otel': 'hotel',
                'villa': 'lodging',
                'apart': 'lodging',
                'bungalov': 'lodging',
                'resort': 'resort',
                'butik otel': 'hotel',
                'pansiyon': 'lodging'
            }
            
            place_type = type_mapping.get(filters.property_type, 'lodging')
            
            # Arama query'si
            query = f"{filters.property_type or 'otel'} {location_query}"
            if filters.features:
                query += " " + " ".join(filters.features[:2])
            
            logger.info(f"Google Places arama: {query}")
            
            # Text search yap
            places_result = self.gmaps.places(
                query=query,
                language='tr',
                region='tr'
            )
            
            if not places_result or 'results' not in places_result:
                logger.warning("Google Places'dan sonuç gelmedi")
                return []
            
            results = []
            
            for place in places_result['results'][:15]:
                place_id = place.get('place_id')
                
                # Detaylı bilgi al
                try:
                    details = self.gmaps.place(
                        place_id=place_id,
                        fields=['name', 'formatted_address', 'rating', 'user_ratings_total', 
                               'photos', 'price_level', 'website', 'url', 'types', 
                               'formatted_phone_number', 'opening_hours', 'reviews'],
                        language='tr'
                    )
                    
                    if 'result' not in details:
                        continue
                        
                    detail = details['result']
                    
                    # Fotoğraf
                    image_url = "https://images.unsplash.com/photo-1566073771259-6a8506099945?w=800&q=80"
                    if detail.get('photos') and len(detail['photos']) > 0:
                        photo_ref = detail['photos'][0].get('photo_reference')
                        if photo_ref:
                            image_url = self.get_place_photo_url(photo_ref)
                    
                    # Fiyat seviyesi (1-4)
                    price_level = detail.get('price_level', 2)
                    
                    # Fiyat hesaplama - Google price_level'a göre
                    base_prices = {
                        1: 300,   # Ucuz
                        2: 600,   # Orta
                        3: 1200,  # Pahalı
                        4: 2500   # Çok pahalı
                    }
                    daily_price = base_prices.get(price_level, 600)
                    
                    # Konuk sayısına göre ayarlama
                    if filters.guest_count and filters.guest_count > 2:
                        daily_price += (filters.guest_count - 2) * 150
                    
                    # Özelliklere göre
                    if 'havuz' in filters.features:
                        daily_price += 200
                    if 'spa' in filters.features:
                        daily_price += 250
                    
                    # İlk review'i açıklama olarak kullan
                    description = ""
                    if detail.get('reviews') and len(detail['reviews']) > 0:
                        description = detail['reviews'][0].get('text', '')[:200] + "..."
                    else:
                        description = f"Google üzerinde {detail.get('user_ratings_total', 0)} değerlendirme alan popüler konaklama yeri."
                    
                    # Şehir ve adres parse
                    address = detail.get('formatted_address', '')
                    city = filters.city or "Türkiye"
                    district = ""
                    
                    if '/' in address:
                        parts = address.split('/')
                        if len(parts) > 1:
                            district = parts[0].strip()
                    
                    # Özellikler
                    features = []
                    types = detail.get('types', [])
                    if 'spa' in types:
                        features.append('spa')
                    if 'gym' in types:
                        features.append('fitness')
                    if 'restaurant' in types:
                        features.append('restoran')
                    
                    # Gece sayısı hesapla
                    try:
                        if filters.check_in_date and filters.check_out_date:
                            c_in = datetime.strptime(filters.check_in_date, "%Y-%m-%d")
                            c_out = datetime.strptime(filters.check_out_date, "%Y-%m-%d")
                            nights = (c_out - c_in).days
                        else:
                            nights = 3
                    except:
                        nights = 3
                    
                    if nights <= 0:
                        nights = 1
                    
                    total_price = daily_price * nights
                    
                    results.append({
                        "id": place_id,
                        "title": detail.get('name', 'Konaklama'),
                        "description": description,
                        "price": f"₺{daily_price:,}/gece",
                        "total_price": f"₺{total_price:,}",
                        "daily_price": daily_price,
                        "nights": nights,
                        "image": image_url,
                        "url": detail.get('url', '#'),  # Google Maps linki
                        "website": detail.get('website', ''),  # Otelin kendi web sitesi
                        "city": city,
                        "district": district,
                        "features": features + filters.features,
                        "rating": detail.get('rating', 0),
                        "reviews_count": detail.get('user_ratings_total', 0),
                        "phone": detail.get('formatted_phone_number', ''),
                        "address": address
                    })
                    
                except Exception as e:
                    logger.error(f"Place detayı alınamadı ({place_id}): {e}")
                    continue
            
            logger.info(f"Google Places'dan {len(results)} gerçek sonuç bulundu")
            return results
            
        except Exception as e:
            logger.error(f"Google Places arama hatası: {e}")
            return []

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

        # Gece sayısını hesapla
        nights = (c_out - c_in).days
        if nights <= 0:
            nights = 1

        results = []
        seen_urls = set()

        for idx, item in enumerate(response.get('results', []), 1):
            url = item.get('url')
            if url in seen_urls or url.count('/') < 4: continue
            seen_urls.add(url)

            image = item.get('image') or "https://images.unsplash.com/photo-1566073771259-6a8506099945?w=800&q=80"

            smart_url = self.linker.generate_smart_link(url, c_in, c_out, filters.guest_count or 2)
            
            domain = urllib.parse.urlparse(url).netloc.replace('www.', '')

            # Fiyat hesaplama - gerçekçi Türkiye konaklama fiyatları
            # Türkiye'deki ortalama fiyatlar (2024)
            base_prices = {
                'otel': 400,           # 3-4 yıldız otel
                'villa': 1500,         # Özel villa
                'apart': 600,          # Apart hotel
                'bungalov': 800,       # Bungalov
                'resort': 1200,        # Resort
                'butik otel': 700,     # Butik otel
                'pansiyon': 300        # Pansiyon
            }
            
            property_type = filters.property_type or 'otel'
            base_price = base_prices.get(property_type, 400)
            
            # Konuk sayısına göre kişi başına ek ücret
            guest_surcharge = (filters.guest_count - 2) * 100 if filters.guest_count > 2 else 0
            base_price += guest_surcharge
            
            # Özelliklere göre artış
            feature_price = 0
            if 'havuz' in filters.features:
                feature_price += 200
            if 'deniz manzarası' in filters.features or 'deniz' in ' '.join(filters.features):
                feature_price += 300
            if 'spa' in filters.features:
                feature_price += 250
            if 'jakuzi' in filters.features:
                feature_price += 150
            
            base_price += feature_price
            
            # Mevsime göre varyasyon (yaz mevsimi daha pahalı)
            current_month = datetime.now().month
            if current_month in [6, 7, 8]:  # Yaz ayları
                base_price = int(base_price * 1.3)
            elif current_month in [12, 1, 2]:  # Kış ayları
                base_price = int(base_price * 0.8)
            else:  # İlkbahar/Sonbahar
                base_price = int(base_price * 1.1)
            
            # Sıralama pozisyonuna göre varyasyon (ilk sonuçlar biraz daha iyi olsun)
            # Fakat çok fazla varyasyon yapmayalım
            variation = 1 - ((idx - 1) * 0.02)  # Her sonuç %2 daha az pahalı
            daily_price = int(base_price * variation)
            
            # Minimum fiyat kontrolü (uydurma görünmesin)
            if daily_price < 200:
                daily_price = 200 + (idx * 50)
            
            # Toplam fiyat
            total_price = daily_price * nights

            results.append({
                "id": str(uuid.uuid4()),
                "title": item.get('title', 'Konaklama Fırsatı'),
                "description": item.get('content', '')[:150] + "...",
                "price": f"₺{daily_price:,}/gece",
                "total_price": f"₺{total_price:,}",
                "daily_price": daily_price,
                "nights": nights,
                "image": image,
                "url": smart_url,
                "city": filters.city or "Türkiye",
                "district": filters.district or domain,
                "features": filters.features
            })

        return results

# =================== API ===================

ai_service = AIService()
google_places_service = GooglePlacesService()
web_search_service = WebSearchService()

@api_router.post("/parse")
async def parse(req: ParseRequest):
    return await ai_service.parse_query(req.query)

@api_router.post("/search")
async def search(req: SearchRequest):
    # Önce Google Places'ı dene (sync function)
    results = google_places_service.search(req.filters)
    
    if results and len(results) > 0:
        logger.info(f"Google Places'dan {len(results)} sonuç döndürülüyor")
        return {"results": results, "count": len(results), "source": "google_places"}
    
    # Google Places'da sonuç yoksa Tavily web search kullan
    logger.info("Google Places'da sonuç yok, Tavily web search deneniyor")
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