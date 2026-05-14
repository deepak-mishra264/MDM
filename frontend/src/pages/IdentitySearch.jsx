import { useState } from "react";
import { useParams } from "react-router-dom";
import { Search as SearchIcon } from "lucide-react";
import { api } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";

export default function IdentitySearch() {
  const { jobId } = useParams();
  const [q, setQ] = useState("");
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);

  const run = async () => {
    if (!q.trim()) return;
    setLoading(true);
    try {
      const { data } = await api.get(`/search`, { params: { q, job_id: jobId } });
      setResults(data);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Search failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="p-6 md:p-8 max-w-[1080px] mx-auto" data-testid="identity-search-page">
      <div className="mb-6">
        <h1 className="font-display text-2xl sm:text-3xl font-bold tracking-tight">Identity Search</h1>
        <p className="text-sm text-[#3C4043] mt-1">
          Sub-second lookups across the Curated Master via Search Index. Try a name, phone, or email fragment.
        </p>
      </div>

      <div className="bg-white border border-[#DADCE0] rounded-md p-5 flex items-center gap-2 shadow-sm">
        <SearchIcon className="h-5 w-5 text-[#5F6368]" />
        <Input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && run()}
          placeholder="Search by name, email, phone…"
          className="border-0 focus-visible:ring-0 text-sm"
          data-testid="search-input"
        />
        <Button onClick={run} disabled={loading} className="bg-[#1A73E8] hover:bg-[#1557B0] text-white" data-testid="search-submit-btn">
          {loading ? "Searching…" : "Search"}
        </Button>
      </div>

      {results && (
        <div className="mt-6 space-y-3">
          <div className="text-sm text-[#5F6368]" data-testid="search-result-count">
            {results.count} matching golden records for <span className="mono text-[#202124]">"{results.query}"</span>
          </div>
          {results.matches.length === 0 ? (
            <div className="bg-white border border-[#DADCE0] rounded-md p-10 text-center text-sm text-[#5F6368]">No matches.</div>
          ) : (
            results.matches.map((m, i) => (
              <div key={i} className="bg-white border border-[#DADCE0] rounded-md p-4 lift" data-testid={`search-result-${i}`}>
                <div className="flex items-center justify-between">
                  <span className="mono text-xs px-2 py-0.5 rounded bg-[#F1F3F4]">{m.enterprise_id}</span>
                  <span className="text-xs text-[#5F6368]">{m.match_method} · {m.source_record_count} source row(s)</span>
                </div>
                <div className="mt-3 grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                  {Object.entries(m).filter(([k]) => k.startsWith("golden_")).map(([k, v]) => (
                    <div key={k}>
                      <div className="text-[11px] uppercase tracking-[0.08em] text-[#5F6368]">{k.replace("golden_", "")}</div>
                      <div className="text-[#202124] truncate">{v ?? "—"}</div>
                    </div>
                  ))}
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
