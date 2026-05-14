import { useEffect, useState } from "react";
import { Save } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

export default function Settings() {
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const { data } = await api.get("/config/gcp");
        setText(JSON.stringify(data, null, 2));
      } catch (e) {
        toast.error("Could not load gcp_config.yaml");
      }
    })();
  }, []);

  const save = async () => {
    setSaving(true);
    try {
      const cfg = JSON.parse(text);
      const { data } = await api.put("/config/gcp", { config: cfg });
      setText(JSON.stringify(data, null, 2));
      toast.success("gcp_config.yaml saved");
    } catch (e) {
      toast.error(e?.response?.data?.detail || e.message || "Save failed (invalid JSON?)");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="p-6 md:p-8 max-w-[920px] mx-auto" data-testid="settings-page">
      <div className="mb-5">
        <h1 className="font-display text-2xl sm:text-3xl font-bold tracking-tight">Settings · GCP Config</h1>
        <p className="text-sm text-[#3C4043] mt-1">
          The persistent <code className="mono text-xs">gcp_config.yaml</code> backing this portal. Edit Project ID, Dataset, Bucket, Vertex AI model, and matching threshold.
        </p>
      </div>

      <div className="bg-white border border-[#DADCE0] rounded-md p-5">
        <Textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          className="mono text-[13px] h-[460px] border-[#DADCE0] bg-[#1F2024] text-[#E8EAED]"
          spellCheck={false}
          data-testid="gcp-config-textarea"
        />
        <div className="mt-4 flex items-center justify-between">
          <p className="text-xs text-[#5F6368]">
            Add <code className="mono">VERTEX_AI_CREDS_PATH</code> to <code className="mono">/app/backend/.env</code> to switch from Preview → Live mode.
          </p>
          <Button onClick={save} disabled={saving} className="bg-[#1A73E8] hover:bg-[#1557B0] text-white" data-testid="save-config-btn">
            <Save className="h-4 w-4 mr-2" />{saving ? "Saving…" : "Save Config"}
          </Button>
        </div>
      </div>
    </div>
  );
}
