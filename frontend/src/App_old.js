import { useState } from "react";
import "@/App.css";
import axios from "axios";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Slider } from "@/components/ui/slider";
import { Loader2, Search, MapPin, DollarSign, ExternalLink, SlidersHorizontal, Calendar as CalendarIcon, X } from "lucide-react";
import { toast } from "sonner";
import { Toaster } from "@/components/ui/sonner";
import { format } from "date-fns";
import { tr } from "date-fns/locale";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const CITIES = [
  "İstanbul", "Ankara", "İzmir", "Antalya", "Bursa", 
  "Adana", "Gaziantep", "Konya", "Muğla", "Trabzon",
  "Alanya", "Bodrum", "Fethiye", "Marmaris", "Kuşadası",
  "Side", "Belek", "Çeşme", "Alaçatı", "Kaş", "Kalkan",
  "Göcek", "Sapanca", "Abant", "Uludağ", "Kapadokya",
  "Pamukkale", "Ayder", "Uzungöl", "Bozcaada", "Gökçeada",
  "Ayvalık", "Assos", "Olympos", "Çıralı", "Dalyan",
  "Datça", "Akyaka", "Şirince", "Foça", "Seferihisar"
];

const PROPERTY_TYPES = [
  { value: "otel", label: "Otel" },
  { value: "villa", label: "Villa" },
  { value: "apart", label: "Apart" },
  { value: "bungalov", label: "Bungalov" },
  { value: "resort", label: "Resort" },
  { value: "butik otel", label: "Butik Otel" },
  { value: "pansiyon", label: "Pansiyon" }
];

// Features removed - users should use AI search for specific features

function App() {
  // AI Search states
  const [aiQuery, setAiQuery] = useState("");
  
  // Manual filter states
  const [showFilters, setShowFilters] = useState(false);
  const [selectedCity, setSelectedCity] = useState("");
  const [selectedPropertyType, setSelectedPropertyType] = useState("");
  const [guestCount, setGuestCount] = useState("");
  const [checkInDate, setCheckInDate] = useState();
  const [checkOutDate, setCheckOutDate] = useState();
  // Features removed
  const [priceRange, setPriceRange] = useState([0, 10000]);
  
  // Results states
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState([]);
  const [source, setSource] = useState("");

  const handleAISearch = async () => {
    if (!aiQuery.trim()) {
      toast.error("Lütfen arama yapabilmek için bir şeyler yazın");
      return;
    }

    setLoading(true);
    setResults([]);
    setSource("");

    try {
      const parseResponse = await axios.post(`${API}/parse`, { query: aiQuery });
      const filters = parseResponse.data;

      const searchResponse = await axios.post(`${API}/search`, { filters });
      const { results: searchResults, source: dataSource } = searchResponse.data;

      setResults(searchResults);
      setSource(dataSource);

      if (searchResults.length === 0) {
        toast.info("Aramanızla eşleşen sonuç bulunamadı. Lütfen farklı kriterler deneyin.");
      } else {
        toast.success(`${searchResults.length} konaklama bulundu!`);
      }
    } catch (error) {
      console.error("Search error:", error);
      toast.error("Arama sırasında bir hata oluştu. Lütfen tekrar deneyin.");
    } finally {
      setLoading(false);
    }
  };

  const handleManualSearch = async () => {
    if (!selectedCity && !selectedPropertyType) {
      toast.error("Lütfen en az şehir veya konaklama tipi seçin");
      return;
    }

    setLoading(true);
    setResults([]);
    setSource("");

    try {
      const filters = {
        city: selectedCity || null,
        district: null,
        price_min: priceRange[0] || null,
        price_max: priceRange[1] || null,
        guest_count: guestCount ? parseInt(guestCount) : null,
        property_type: selectedPropertyType || null,
        features: [],
        check_in_date: checkInDate ? format(checkInDate, "d MMMM yyyy", { locale: tr }) : null,
        check_out_date: checkOutDate ? format(checkOutDate, "d MMMM yyyy", { locale: tr }) : null,
        raw_query: "manual"
      };

      const searchResponse = await axios.post(`${API}/search`, { filters });
      const { results: searchResults, source: dataSource } = searchResponse.data;

      setResults(searchResults);
      setSource(dataSource);

      if (searchResults.length === 0) {
        toast.info("Aramanızla eşleşen sonuç bulunamadı.");
      } else {
        toast.success(`${searchResults.length} konaklama bulundu!`);
      }
    } catch (error) {
      console.error("Search error:", error);
      toast.error("Arama sırasında bir hata oluştu.");
    } finally {
      setLoading(false);
    }
  };

  // Features removed

  const clearFilters = () => {
    setSelectedCity("");
    setSelectedPropertyType("");
    setGuestCount("");
    setCheckInDate(undefined);
    setCheckOutDate(undefined);
    setPriceRange([0, 10000]);
  };

  const handleKeyPress = (e) => {
    if (e.key === "Enter") {
      handleAISearch();
    }
  };

  return (
    <div className="App">
      <Toaster position="top-center" richColors />
      
      {/* Header Section */}
      <div className="hero-section">
        <div className="hero-overlay" />
        <div className="hero-content">
          <h1 className="hero-title" data-testid="app-title">
            AI Konaklama Asistanı
          </h1>
          <p className="hero-subtitle" data-testid="app-subtitle">
            Türkiye'nin en akıllı konaklama arama motoru
          </p>
          
          {/* AI Search Bar */}
          <div className="search-container" data-testid="search-container">
            <div className="search-bar">
              <Search className="search-icon" />
              <Input
                data-testid="search-input"
                type="text"
                placeholder="Nereye, kaç kişi, hangi tarihlerde, hangi özelliklerde konaklama arıyorsunuz?"
                value={aiQuery}
                onChange={(e) => setAiQuery(e.target.value)}
                onKeyPress={handleKeyPress}
                disabled={loading}
                className="search-input"
              />
            </div>
            <Button
              data-testid="search-button"
              onClick={handleAISearch}
              disabled={loading}
              className="search-button"
            >
              {loading ? (
                <>
                  <Loader2 className="animate-spin mr-2" size={20} />
                  Aranıyor...
                </>
              ) : (
                "AI'ya Sor"
              )}
            </Button>
          </div>
          
          {/* Filter Toggle Button */}
          <div className="filter-toggle-container">
            <Button
              data-testid="toggle-filters-button"
              onClick={() => setShowFilters(!showFilters)}
              variant="outline"
              className="filter-toggle-button"
            >
              <SlidersHorizontal size={18} className="mr-2" />
              {showFilters ? "Filtreleri Gizle" : "Gelişmiş Filtreler"}
            </Button>
          </div>
          
          {/* Example Queries */}
          {!showFilters && (
            <div className="example-queries" data-testid="example-queries">
              <span className="example-label">Örnek aramalar:</span>
              <button
                data-testid="example-query-1"
                onClick={() => setAiQuery("Antalya'da 4 kişilik denize sıfır havuzlu villa 2 Eylül - 5 Eylül")}
                className="example-chip"
              >
                Antalya 2-5 Eylül villa
              </button>
              <button
                data-testid="example-query-2"
                onClick={() => setAiQuery("Bodrum'da 3000-6000 TL arası otel 15-20 Haziran")}
                className="example-chip"
              >
                Bodrum 15-20 Haziran otel
              </button>
              <button
                data-testid="example-query-3"
                onClick={() => setAiQuery("Sapanca'da şömineli bungalov 10 Aralık")}
                className="example-chip"
              >
                Sapanca 10 Aralık bungalov
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Advanced Filters Panel */}
      {showFilters && (
        <div className="filters-panel" data-testid="filters-panel">
          <div className="filters-container">
            <div className="filters-header">
              <h3 className="filters-title">Gelişmiş Filtreler</h3>
              <Button
                variant="ghost"
                size="sm"
                onClick={clearFilters}
                className="clear-filters-button"
                data-testid="clear-filters-button"
              >
                <X size={16} className="mr-1" />
                Temizle
              </Button>
            </div>

            <div className="filters-grid">
              {/* Property Type */}
              <div className="filter-group">
                <Label className="filter-label">Konaklama Tipi</Label>
                <div className="property-type-pills">
                  {PROPERTY_TYPES.map((type) => (
                    <button
                      key={type.value}
                      data-testid={`property-type-${type.value}`}
                      onClick={() => setSelectedPropertyType(
                        selectedPropertyType === type.value ? "" : type.value
                      )}
                      className={`property-pill ${selectedPropertyType === type.value ? 'active' : ''}`}
                    >
                      {type.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* City */}
              <div className="filter-group">
                <Label className="filter-label">Şehir</Label>
                <Select value={selectedCity} onValueChange={setSelectedCity}>
                  <SelectTrigger data-testid="city-select" className="filter-select">
                    <SelectValue placeholder="Şehir seçin" />
                  </SelectTrigger>
                  <SelectContent>
                    {CITIES.map((city) => (
                      <SelectItem key={city} value={city}>{city}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {/* Guest Count */}
              <div className="filter-group">
                <Label className="filter-label">Kişi Sayısı</Label>
                <Input
                  data-testid="guest-count-input"
                  type="number"
                  min="1"
                  max="20"
                  placeholder="Kaç kişi?"
                  value={guestCount}
                  onChange={(e) => setGuestCount(e.target.value)}
                  className="filter-input"
                />
              </div>

              {/* Check-in Date */}
              <div className="filter-group">
                <Label className="filter-label">Giriş Tarihi</Label>
                <Popover>
                  <PopoverTrigger asChild>
                    <Button
                      data-testid="check-in-date-button"
                      variant="outline"
                      className="date-picker-button"
                    >
                      <CalendarIcon size={16} className="mr-2" />
                      {checkInDate ? format(checkInDate, "d MMMM yyyy", { locale: tr }) : "Tarih seçin"}
                    </Button>
                  </PopoverTrigger>
                  <PopoverContent className="date-picker-content">
                    <Calendar
                      mode="single"
                      selected={checkInDate}
                      onSelect={setCheckInDate}
                      locale={tr}
                      disabled={(date) => date < new Date()}
                    />
                  </PopoverContent>
                </Popover>
              </div>

              {/* Check-out Date */}
              <div className="filter-group">
                <Label className="filter-label">Çıkış Tarihi</Label>
                <Popover>
                  <PopoverTrigger asChild>
                    <Button
                      data-testid="check-out-date-button"
                      variant="outline"
                      className="date-picker-button"
                    >
                      <CalendarIcon size={16} className="mr-2" />
                      {checkOutDate ? format(checkOutDate, "d MMMM yyyy", { locale: tr }) : "Tarih seçin"}
                    </Button>
                  </PopoverTrigger>
                  <PopoverContent className="date-picker-content">
                    <Calendar
                      mode="single"
                      selected={checkOutDate}
                      onSelect={setCheckOutDate}
                      locale={tr}
                      disabled={(date) => date < (checkInDate || new Date())}
                    />
                  </PopoverContent>
                </Popover>
              </div>

              {/* Price Range */}
              <div className="filter-group full-width">
                <Label className="filter-label">
                  Fiyat Aralığı: {priceRange[0]} TL - {priceRange[1]} TL
                </Label>
                <Slider
                  data-testid="price-slider"
                  value={priceRange}
                  onValueChange={setPriceRange}
                  min={0}
                  max={10000}
                  step={500}
                  className="price-slider"
                />
              </div>
            </div>
            
            <div className="ai-suggestion-note">
              <p>💡 <strong>İpucu:</strong> Daha spesifik özellikler (havuzlu, şömineli, denize sıfır vb.) için yukarıdaki <strong>"AI'ya Sor"</strong> özelliğini kullanın.</p>
            </div>

            {/* Search Button */}
            <div className="filters-footer">
              <Button
                data-testid="manual-search-button"
                onClick={handleManualSearch}
                disabled={loading}
                className="manual-search-button"
              >
                {loading ? (
                  <>
                    <Loader2 className="animate-spin mr-2" size={20} />
                    Aranıyor...
                  </>
                ) : (
                  <>
                    <Search size={20} className="mr-2" />
                    Ara
                  </>
                )}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Results Section */}
      {results.length > 0 && (
        <div className="results-section" data-testid="results-section">
          <div className="results-header">
            <h2 className="results-title" data-testid="results-count">
              {results.length} Konaklama Bulundu
            </h2>
            <Badge variant="outline" className="source-badge" data-testid="source-badge">
              {source === "web" ? "Web'den Alındı" : "Yerel Verilerden"}
            </Badge>
          </div>
          
          <div className="results-grid" data-testid="results-grid">
            {results.map((result, index) => (
              <Card key={index} className="accommodation-card" data-testid={`result-card-${index}`}>
                {result.image && (
                  <div className="card-image-container">
                    <img
                      src={result.image}
                      alt={result.title}
                      className="card-image"
                      data-testid={`result-image-${index}`}
                    />
                    {result.price && (
                      <div className="price-badge" data-testid={`result-price-${index}`}>
                        <DollarSign size={16} />
                        {result.price}
                      </div>
                    )}
                  </div>
                )}
                
                <CardHeader>
                  <CardTitle className="card-title" data-testid={`result-title-${index}`}>
                    {result.title}
                  </CardTitle>
                  <CardDescription className="card-location" data-testid={`result-location-${index}`}>
                    <MapPin size={14} className="inline mr-1" />
                    {result.city}
                    {result.district && `, ${result.district}`}
                  </CardDescription>
                </CardHeader>
                
                <CardContent>
                  <p className="card-description" data-testid={`result-description-${index}`}>
                    {result.description}
                  </p>
                  
                  {result.features && result.features.length > 0 && (
                    <div className="features-container" data-testid={`result-features-${index}`}>
                      {result.features.slice(0, 6).map((feature, idx) => (
                        <Badge key={idx} variant="secondary" className="feature-badge">
                          {feature}
                        </Badge>
                      ))}
                    </div>
                  )}
                </CardContent>
                
                <CardFooter>
                  {result.url && result.url !== "#" && (
                    <a 
                      href={result.url} 
                      target="_blank" 
                      rel="noopener noreferrer"
                      style={{ width: '100%' }}
                    >
                      <Button
                        data-testid={`result-detail-button-${index}`}
                        variant="outline"
                        className="detail-button"
                        style={{ width: '100%' }}
                      >
                        <ExternalLink size={16} className="mr-2" />
                        Detay
                      </Button>
                    </a>
                  )}
                </CardFooter>
              </Card>
            ))}
          </div>
        </div>
      )}
      
      {/* Footer */}
      <footer className="app-footer">
        <p>© 2025 AI Konaklama Asistanı - Claude Sonnet 4 ile güçlendirilmiştir</p>
      </footer>
    </div>
  );
}

export default App;