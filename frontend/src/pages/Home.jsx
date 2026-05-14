import { useCallback, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { UploadCloud, FileSpreadsheet, Sparkles, ArrowRight, Database, GitBranch, Search } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";

export default function Home() {
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const inputRef = useRef(null);
  const navigate = useNavigate();

  const handleFiles = useCallback(async (file) => {
    if (!file) return;
    const allowed = [".csv", ".json", ".xlsx", ".xls"];
    if (!allowed.some((ext) => file.name.toLowerCase().endsWith(ext))) {
      toast.error("Unsupported file. Use CSV, Excel, or JSON.");
      return;
    }
    setUploading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const { data } = await api.post("/upload", form, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      toast.success(`Landed in GCS · ${data.row_count} rows · ${data.columns.length} columns`);
      navigate(`/configure/${data.job_id}`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Upload failed");
    } finally {
      setUploading(false);
    }
  }, [navigate]);

  const onDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer.files?.[0];
    handleFiles(f);
  };

  const loadDemo = async () => {
    setUploading(true);
    try {
      const { data } = await api.post("/demo/load");
      toast.success(`Demo loaded · ${data.row_count} customer records (with duplicates)`);
      navigate(`/configure/${data.job_id}`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not load demo");
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="relative">
      <div className="absolute inset-0 bg-grid pointer-events-none" aria-hidden="true" />

      <div className="relative px-6 md:px-8 pt-10 md:pt-14 pb-16">
        <div className="max-w-3xl mx-auto text-center reveal">
          <div className="inline-flex items-center gap-2 text-[11px] uppercase tracking-[0.18em] text-[#5F6368] mb-4">
            <Sparkles className="h-3.5 w-3.5 text-[#1A73E8]" />
            <span>Agent-Driven · BigQuery-Native · GCP Lifecycle</span>
          </div>
          <h1 className="font-display text-4xl sm:text-5xl lg:text-6xl font-bold tracking-tight text-[#202124]">
            Searce MDM
          </h1>
          <p className="mt-4 text-base sm:text-lg text-[#3C4043] max-w-2xl mx-auto leading-relaxed">
            An AI-MDM Intelligence & Identity Portal. Describe your matching and
            survivorship logic in plain English — the agent converts it to scalable
            BigQuery SQL across a 3-tier lifecycle.
          </p>
        </div>

        {/* Google-styled centered upload card */}
        <div className="max-w-2xl mx-auto mt-10 reveal reveal-delay-1">
          <div
            className={`drop-zone bg-white border border-[#DADCE0] rounded-xl shadow-[0_1px_2px_rgba(60,64,67,0.08)] ${
              dragOver ? "active" : ""
            }`}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={onDrop}
            data-testid="hero-upload-card"
          >
            <div className="px-7 py-6 border-b border-[#DADCE0] flex items-center gap-3">
              <Database className="h-5 w-5 text-[#1A73E8]" />
              <div>
                <div className="font-display font-semibold text-[15px]">Create MDM Job · Data Intake</div>
                <div className="text-xs text-[#5F6368]">Upload a CSV, Excel, or JSON file. Lands in GCS, then flows into BigQuery.</div>
              </div>
            </div>
            <label
              className="block px-7 py-12 text-center cursor-pointer"
              onClick={() => inputRef.current?.click()}
              data-testid="upload-dropzone"
            >
              <input
                ref={inputRef}
                type="file"
                accept=".csv,.xlsx,.xls,.json"
                className="hidden"
                onChange={(e) => handleFiles(e.target.files?.[0])}
                data-testid="upload-file-input"
              />
              <div className="flex flex-col items-center">
                <div className="h-14 w-14 rounded-full bg-[#E8F0FE] flex items-center justify-center mb-3">
                  <UploadCloud className="h-7 w-7 text-[#1A73E8]" />
                </div>
                <div className="font-medium text-[#202124]">
                  {uploading ? "Uploading…" : "Drop file here, or click to browse"}
                </div>
                <div className="text-xs text-[#5F6368] mt-1">CSV · XLSX · JSON · up to 100k rows</div>
              </div>
            </label>
            <div className="px-7 py-4 border-t border-[#DADCE0] bg-[#F8F9FA] flex items-center justify-between">
              <div className="flex items-center gap-2 text-xs text-[#5F6368]">
                <FileSpreadsheet className="h-4 w-4" />
                <span>No file? Use the bundled customer dataset with intentional duplicates.</span>
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={loadDemo}
                disabled={uploading}
                className="border-[#DADCE0] text-[#1A73E8] hover:bg-[#E8F0FE]"
                data-testid="load-demo-button"
              >
                Try the demo
                <ArrowRight className="ml-1.5 h-3.5 w-3.5" />
              </Button>
            </div>
          </div>
          <p className="text-center text-xs text-[#5F6368] mt-3">
            Files are written to <span className="mono">gs://&lt;bucket&gt;/landing/&lt;job_id&gt;/</span> · zero PII leaves your project in live mode.
          </p>
        </div>

        {/* How it works */}
        <div className="max-w-5xl mx-auto mt-16 grid sm:grid-cols-3 gap-4 reveal reveal-delay-2">
          {[
            { icon: GitBranch, title: "1 · Configure", text: "Pick exact-match keys, fuzzy attributes, and weights. Write survivorship intent in plain English." },
            { icon: Sparkles, title: "2 · Agent Strategy", text: "The intent agent translates your rules into a BigQuery execution plan. You confirm." },
            { icon: Search, title: "3 · Curated Identity", text: "Get Master + Suspect tables with per-attribute match explanations and a search index." },
          ].map((step) => {
            const Icon = step.icon;
            return (
              <div key={step.title} className="bg-white border border-[#DADCE0] rounded-lg p-5 lift">
                <Icon className="h-5 w-5 text-[#1A73E8] mb-3" />
                <div className="font-display font-semibold text-sm text-[#202124]">{step.title}</div>
                <div className="text-xs text-[#5F6368] mt-1.5 leading-relaxed">{step.text}</div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
