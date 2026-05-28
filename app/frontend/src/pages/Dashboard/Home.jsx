import React, { useState } from "react";
import ArticleCard from "../../components/cards/ArticleCard";
import { fetchArticles } from "../../api/newsApi";

function Home() {
  const [brand, setBrand] = useState("");
  const [articles, setArticles] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSearch = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const data = await fetchArticles(brand);
      setArticles(Array.isArray(data) ? data : []);
    } catch (err) {
      setArticles([]);
      setError("Failed to fetch articles");
    }
    setLoading(false);
  };

  return (
    <div style={{ maxWidth: 600, margin: "2rem auto" }}>
      <form onSubmit={handleSearch} style={{ display: "flex", marginBottom: 24 }}>
        <input
          type="text"
          value={brand}
          onChange={e => setBrand(e.target.value)}
          placeholder="Search Brand..."
          style={{ flex: 1, padding: 8, fontSize: 16 }}
        />
        <button type="submit" style={{ marginLeft: 8, padding: "8px 16px" }}>🔍</button>
      </form>
      {loading && <p>Loading...</p>}
      {error && <p style={{ color: "red" }}>{error}</p>}
      {!error && articles.length === 0 && !loading && <p>No articles found.</p>}
      {articles.map((article, idx) => (
        <ArticleCard key={idx} {...article} />
      ))}
    </div>
  );
}

export default Home;
