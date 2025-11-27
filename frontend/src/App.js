import { useState } from "react";
import "@/App.css";
import axios from "axios";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Loader2, Search, MapPin, DollarSign, Home, ExternalLink } from "lucide-react";
import { toast } from "sonner";
import { Toaster } from "@/components/ui/sonner";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

function App() {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState([]);
  const [source, setSource] = useState("");

  const handleSearch = async () => {
    if (!query.trim()) {
      toast.error("Lütfen arama yapabilmek için bir şeyler yazın");
      return;
    }

    setLoading(true);
    setResults([]);
    setSource("");

    try {
      // Step 1: Parse the query
      const parseResponse = await axios.post(`${API}/parse`, { query });
      const filters = parseResponse.data;

      // Step 2: Search with filters
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

  const handleKeyPress = (e) => {
    if (e.key === "Enter") {
      handleSearch();
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
          
          {/* Search Bar */}
          <div className="search-container" data-testid="search-container">
            <div className="search-bar">
              <Search className="search-icon" />
              <Input
                data-testid="search-input"
                type="text"
                placeholder="Nereye, kaç kişi, hangi özelliklerde konaklama arıyorsunuz?"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyPress={handleKeyPress}
                disabled={loading}
                className="search-input"
              />
            </div>
            <Button
              data-testid="search-button"
              onClick={handleSearch}
              disabled={loading}
              className="search-button"
            >
              {loading ? (
                <>
                  <Loader2 className="animate-spin mr-2" size={20} />
                  Aranıyor...
                </>
              ) : (
                "Ara"
              )}
            </Button>
          </div>
          
          {/* Example Queries */}
          <div className="example-queries" data-testid="example-queries">
            <span className="example-label">Örnek aramalar:</span>
            <button
              data-testid="example-query-1"
              onClick={() => setQuery("Antalya'da 4 kişilik denize sıfır havuzlu villa")}
              className="example-chip"
            >
              Antalya'da 4 kişilik denize sıfır havuzlu villa
            </button>
            <button
              data-testid="example-query-2"
              onClick={() => setQuery("Bodrum'da 3000-6000 TL arası otel")}
              className="example-chip"
            >
              Bodrum'da 3000-6000 TL arası otel
            </button>
            <button
              data-testid="example-query-3"
              onClick={() => setQuery("Sapanca'da şömineli bungalov")}
              className="example-chip"
            >
              Sapanca'da şömineli bungalov
            </button>
          </div>
        </div>
      </div>

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
                    <Button
                      data-testid={`result-detail-button-${index}`}
                      variant="outline"
                      className="detail-button"
                      onClick={() => window.open(result.url, "_blank")}
                    >
                      <ExternalLink size={16} className="mr-2" />
                      Detay
                    </Button>
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