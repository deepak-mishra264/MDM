import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ChevronLeft, ChevronRight, Download, Search, Sparkles, AlertTriangle } from "lucide-react";
import { toast } from "sonner";
import { api, API } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";

const PAGE_SIZE = 50;

export default function Results() {
  const { jobId } = useParams();
  const navigate = useNavigate();

  const [masterPage, setMasterPage] = useState({ rows: [], total: 0, offset: 0, has_more: false });
  const [suspectPage, setSuspectPage] = useState({ rows: [], total: 0, offset: 0, has_more: false });
  const [masterLoading, setMasterLoading] = useState(false);
  const [suspectLoading, setSuspectLoading] = useState(false);

  const loadMaster = useCallback(async (offset = 0) => {
    setMasterLoading(true);
    try {
      const { data } = await api.get(`/results/master/${jobId}`, { params: { offset, limit: PAGE_SIZE } });
      setMasterPage(data);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not load master records");
    } finally {
      setMasterLoading(false);
    }
  }, [jobId]);

  const loadSuspect = useCallback(async (offset = 0) => {
    setSuspectLoading(true);
    try {
      const { data } = await api.get(`/results/suspect/${jobId}`, { params: { offset, limit: PAGE_SIZE } });
      setSuspectPage(data);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not load suspect records");
    } finally {
      setSuspectLoading(false);
    }
  }, [jobId]);

  useEffect(() => {
    (async () => {
      try {
        await Promise.all([loadMaster(0), loadSuspect(0)]);
      } catch (e) {
        toast.error("No results yet — execute the pipeline first");
        navigate(`/strategy/${jobId}`);
      }
    })();
  }, [jobId, loadMaster, loadSuspect, navigate]);

  const masterCols = masterPage.rows[0]
    ? Object.keys(masterPage.rows[0]).filter((c) => c !== "ingested_at")
    : [];
  const suspectCols = suspectPage.rows[0]
    ? Object.keys(suspectPage.rows[0]).filter((c) => c !== "ingested_at")
    : [];

  return (
    <div className="p-6 md:p-8 max-w-[1480px] mx-auto" data-testid="results-page">
      <div className="flex items-start justify-between mb-5">
        <div>
          <div className="text-[11px] uppercase tracking-[0.18em] text-[#5F6368] mb-1">Curated Layer</div>
          <h1 className="font-display text-2xl sm:text-3xl font-bold tracking-tight">Master & Suspect Records</h1>
          <p className="text-sm text-[#3C4043] mt-1 max-w-2xl">
            Synthetic golden attributes built per the agent-interpreted survivorship logic.
            Suspects include a per-attribute match explanation.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => navigate(`/search/${jobId}`)} className="border-[#DADCE0] text-[#1A73E8] hover:bg-[#E8F0FE]" data-testid="open-search-btn">
            <Search className="h-4 w-4 mr-2" />Identity Search
          </Button>
          <a href={`${API}/sql/${jobId}/download`} target="_blank" rel="noreferrer" data-testid="download-sql-link">
            <Button variant="outline" className="border-[#DADCE0]">
              <Download className="h-4 w-4 mr-2" />Download SQL
            </Button>
          </a>
        </div>
      </div>

      <Tabs defaultValue="master">
        <TabsList className="bg-[#F1F3F4]">
          <TabsTrigger value="master" data-testid="tab-master">
            <Sparkles className="h-4 w-4 mr-1.5" />Master · {masterPage.total}
          </TabsTrigger>
          <TabsTrigger value="suspect" data-testid="tab-suspect">
            <AlertTriangle className="h-4 w-4 mr-1.5" />Suspect · {suspectPage.total}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="master" className="mt-4">
          <DataTable
            rows={masterPage.rows}
            cols={masterCols}
            testIdPrefix="master"
            renderCell={(c, v) => {
              if (c === "match_method") {
                const map = { unique: "bg-[#F1F3F4] text-[#5F6368]", deterministic: "bg-[#E6F4EA] text-[#188038]", probabilistic: "bg-[#E8F0FE] text-[#1A73E8]" };
                return <Badge className={`${map[v] || ""} hover:opacity-100`}>{v}</Badge>;
              }
              if (c === "enterprise_id") return <span className="mono text-xs">{v}</span>;
              return v ?? "—";
            }}
          />
          <Pager page={masterPage} loading={masterLoading} onChange={loadMaster} testIdPrefix="master" />
        </TabsContent>

        <TabsContent value="suspect" className="mt-4">
          <DataTable
            rows={suspectPage.rows}
            cols={suspectCols}
            testIdPrefix="suspect"
            renderCell={(c, v) => {
              if (c === "suspect_score") {
                const num = Number(v || 0);
                const tone = num >= 90 ? "bg-[#FCE8E6] text-[#D93025]" : num >= 80 ? "bg-[#FEF7E0] text-[#9C5500]" : "bg-[#E8F0FE] text-[#1A73E8]";
                return <Badge className={`${tone} hover:opacity-100`}>{num.toFixed(2)}%</Badge>;
              }
              if (c === "parent_enterprise_id" || c === "suspect_record_uid") return <span className="mono text-xs">{v}</span>;
              if (c === "match_explanation") return <span className="text-[12px] text-[#3C4043]">{v}</span>;
              return v ?? "—";
            }}
          />
          <Pager page={suspectPage} loading={suspectLoading} onChange={loadSuspect} testIdPrefix="suspect" />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function DataTable({ rows, cols, renderCell, testIdPrefix }) {
  if (!rows.length) {
    return <div className="bg-white border border-[#DADCE0] rounded-md p-10 text-center text-sm text-[#5F6368]" data-testid={`${testIdPrefix}-empty`}>No records.</div>;
  }
  return (
    <div className="bg-white border border-[#DADCE0] rounded-md overflow-hidden">
      <div className="overflow-auto max-h-[calc(100vh-340px)]">
        <table className="w-full table-dense" data-testid={`${testIdPrefix}-table`}>
          <thead className="sticky top-0 z-10">
            <tr>
              {cols.map((c) => (
                <th key={c} className="text-left">{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-t border-[#DADCE0] hover:bg-[#F8F9FA]" data-testid={`${testIdPrefix}-row-${i}`}>
                {cols.map((c) => (
                  <td key={c} className="align-top text-[13px] text-[#202124]">
                    {renderCell ? renderCell(c, r[c], r) : (r[c] ?? "—")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Pager({ page, loading, onChange, testIdPrefix }) {
  const start = page.total === 0 ? 0 : page.offset + 1;
  const end = Math.min(page.offset + page.limit, page.total);
  const canPrev = page.offset > 0 && !loading;
  const canNext = page.has_more && !loading;
  return (
    <div className="flex items-center justify-between mt-3 px-1 text-xs text-[#5F6368]" data-testid={`${testIdPrefix}-pager`}>
      <div data-testid={`${testIdPrefix}-pager-info`}>
        {page.total > 0 ? <>Showing <strong className="text-[#202124]">{start}–{end}</strong> of <strong className="text-[#202124]">{page.total.toLocaleString()}</strong></> : "No records"}
      </div>
      <div className="flex items-center gap-1">
        <Button
          size="sm"
          variant="outline"
          className="h-8 px-2 border-[#DADCE0]"
          disabled={!canPrev}
          onClick={() => onChange(Math.max(0, page.offset - page.limit))}
          data-testid={`${testIdPrefix}-prev-btn`}
        >
          <ChevronLeft className="h-3.5 w-3.5" />
        </Button>
        <Button
          size="sm"
          variant="outline"
          className="h-8 px-2 border-[#DADCE0]"
          disabled={!canNext}
          onClick={() => onChange(page.offset + page.limit)}
          data-testid={`${testIdPrefix}-next-btn`}
        >
          <ChevronRight className="h-3.5 w-3.5" />
        </Button>
      </div>
    </div>
  );
}
