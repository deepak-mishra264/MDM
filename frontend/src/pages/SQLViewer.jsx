import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { Copy, Download } from "lucide-react";
import { toast } from "sonner";
import { api, API } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";

const TABS = [
  { key: "raw_layer", label: "Raw" },
  { key: "staging_layer", label: "Staging" },
  { key: "curated_master", label: "Master" },
  { key: "curated_suspect", label: "Suspect" },
  { key: "search_index", label: "Search Index" },
];

export default function SQLViewer() {
  const { jobId } = useParams();
  const [sql, setSql] = useState(null);

  useEffect(() => {
    (async () => {
      try {
        const { data } = await api.get(`/sql/${jobId}`);
        setSql(data);
      } catch (e) {
        toast.error(e?.response?.data?.detail || "Could not load SQL");
      }
    })();
  }, [jobId]);

  const copy = (text) => {
    navigator.clipboard.writeText(text);
    toast.success("Copied to clipboard");
  };

  return (
    <div className="p-6 md:p-8 max-w-[1200px] mx-auto" data-testid="sql-viewer-page">
      <div className="flex items-start justify-between mb-5">
        <div>
          <h1 className="font-display text-2xl sm:text-3xl font-bold tracking-tight">Generated BigQuery SQL</h1>
          <p className="text-sm text-[#3C4043] mt-1 max-w-2xl">
            The exact statements your agent will execute against BigQuery in live mode. Copy individual layers or download the full script.
          </p>
        </div>
        <a href={`${API}/sql/${jobId}/download`} target="_blank" rel="noreferrer" data-testid="download-full-sql-link">
          <Button variant="outline" className="border-[#DADCE0]">
            <Download className="h-4 w-4 mr-2" />Download .sql
          </Button>
        </a>
      </div>

      {!sql ? (
        <div className="bg-white border border-[#DADCE0] rounded-md p-10 text-center text-sm text-[#5F6368]" data-testid="sql-loading">Loading SQL…</div>
      ) : (
        <Tabs defaultValue="raw_layer">
          <TabsList className="bg-[#F1F3F4] flex-wrap h-auto">
            {TABS.map((t) => (
              <TabsTrigger key={t.key} value={t.key} data-testid={`sql-tab-${t.key}`}>{t.label}</TabsTrigger>
            ))}
          </TabsList>
          {TABS.map((t) => (
            <TabsContent key={t.key} value={t.key} className="mt-4">
              <div className="relative">
                <pre className="sql-block" data-testid={`sql-block-${t.key}`}>{sql[t.key]}</pre>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => copy(sql[t.key])}
                  className="absolute top-3 right-3 bg-[#3C4043] text-white hover:bg-[#202124] hover:text-white border border-[#5F6368]/40"
                  data-testid={`copy-${t.key}-btn`}
                >
                  <Copy className="h-3.5 w-3.5 mr-1.5" />Copy
                </Button>
              </div>
            </TabsContent>
          ))}
        </Tabs>
      )}
    </div>
  );
}
