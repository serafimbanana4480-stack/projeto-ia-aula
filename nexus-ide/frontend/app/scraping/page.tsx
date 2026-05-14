"use client";
import { useState } from "react";
import { motion } from "framer-motion";
import TopBar from "../../components/layout/TopBar";
import Sidebar from "../../components/layout/Sidebar";
import BottomHUD from "../../components/layout/BottomHUD";
import {
  Globe,
  Search,
  ExternalLink,
  Loader2,
  AlertCircle,
} from "lucide-react";
import { apiUrl } from "../../lib/api";

interface SearchResult {
  title: string;
  url: string;
  snippet: string;
}

export default function ScrapingPage() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSearch = async () => {
    if (!query.trim()) return;

    setLoading(true);
    setError("");
    setResults([]);

    try {
      const response = await fetch(apiUrl("/api/web_search"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query, max_results: 10 }),
      });

      const data = await response.json();

      if (data.error) {
        setError(data.error);
      } else if (Array.isArray(data)) {
        setResults(data);
      } else {
        setError("Unexpected response format");
      }
    } catch (err) {
      setError("Failed to perform search. Make sure backend is running.");
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex h-screen flex-col bg-nexus-bg">
      <TopBar />

      <div className="flex flex-1 overflow-hidden">
        <Sidebar />

        <main className="flex-1 overflow-auto p-6">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="max-w-4xl mx-auto"
          >
            <div className="mb-6 flex items-center gap-3">
              <Globe className="h-6 w-6 text-nexus-accent" />
              <h1 className="text-2xl font-bold">AI Web Scraping</h1>
            </div>

            {/* Search Input */}
            <div className="mb-6 rounded border border-nexus-border bg-nexus-panel/50 p-4">
              <div className="flex gap-2">
                <input
                  type="text"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyPress={(e) => e.key === "Enter" && handleSearch()}
                  placeholder="Enter search query..."
                  className="flex-1 rounded bg-black/30 px-4 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-nexus-accent"
                  disabled={loading}
                />
                <button
                  onClick={handleSearch}
                  disabled={loading || !query.trim()}
                  className="flex items-center gap-2 rounded bg-nexus-accent px-4 py-2 text-sm font-medium text-black hover:bg-nexus-accent/80 disabled:opacity-50"
                >
                  {loading ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Search className="h-4 w-4" />
                  )}
                  Search
                </button>
              </div>

              {error && (
                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  className="mt-3 flex items-center gap-2 text-sm text-red-400"
                >
                  <AlertCircle className="h-4 w-4" />
                  {error}
                </motion.div>
              )}
            </div>

            {/* Results */}
            {loading && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="flex items-center justify-center py-12"
              >
                <Loader2 className="h-8 w-8 animate-spin text-nexus-accent" />
              </motion.div>
            )}

            {!loading && results.length > 0 && (
              <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                className="space-y-3"
              >
                <div className="text-sm text-gray-400">
                  Found {results.length} results
                </div>
                {results.map((result, index) => (
                  <motion.div
                    key={index}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: index * 0.05 }}
                    className="rounded border border-nexus-border bg-nexus-panel/50 p-4 hover:bg-nexus-border/30 transition-colors"
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex-1 min-w-0">
                        <h3 className="font-medium text-sm mb-1">
                          {result.title}
                        </h3>
                        <p className="text-xs text-gray-400 mb-2">
                          {result.snippet}
                        </p>
                        <a
                          href={result.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="flex items-center gap-1 text-xs text-nexus-accent hover:underline"
                        >
                          <ExternalLink className="h-3 w-3" />
                          {result.url}
                        </a>
                      </div>
                    </div>
                  </motion.div>
                ))}
              </motion.div>
            )}

            {!loading && results.length === 0 && !error && query && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="text-center py-12 text-gray-500"
              >
                <Globe className="mx-auto mb-3 h-12 w-12 text-nexus-border" />
                <p className="text-sm">No results found</p>
                <p className="text-xs">Try a different search query</p>
              </motion.div>
            )}

            {!loading && !query && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="text-center py-12 text-gray-500"
              >
                <Globe className="mx-auto mb-3 h-12 w-12 text-nexus-accent" />
                <p className="text-sm">AI-Powered Web Scraping</p>
                <p className="text-xs">
                  Search the web using DuckDuckGo with AI analysis
                </p>
              </motion.div>
            )}
          </motion.div>
        </main>
      </div>

      <BottomHUD />
    </div>
  );
}
