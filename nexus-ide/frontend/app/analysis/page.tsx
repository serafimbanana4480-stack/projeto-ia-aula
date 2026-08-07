import MetricsPage from "../analytics/page";

// The sidebar's "Métricas" entry points to /analysis. Keep the richer
// implementation in the analytics module so the legacy /analytics URL and
// the canonical product navigation render the same source of truth.
export default MetricsPage;
