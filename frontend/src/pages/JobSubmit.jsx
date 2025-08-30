import { useState } from "react";

const GITHUB_REPO_REGEX = /^https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/?$/;

export default function JobSubmit() {
    const [jobId, setJobId] = useState(null);
    const [error, setError] = useState(null);
    const [loading, setLoading] = useState(false);
    const [repoUrl, setRepoUrl] = useState("");

    const apiBaseRaw = import.meta.env.VITE_API_BASE_URL;
    const apiBase = apiBaseRaw ? apiBaseRaw.replace(/\/+$/, "") : "";

    const validate = (value) => {
        if (!value || value.trim().length === 0) return "Enter Guithub URL";
        if (!GITHUB_REPO_REGEX.test(value.trim()))
            return "Enter by the following format: https://github.com/owner/repo";
        return "";
    };

    const onSubmit = async (e) => {
        e.preventDefault();
        setJobId("");
        setError("");

        const v = validate(repoUrl);
        if (v) {
            setError(v);
            return;
        }
        if (!apiBase) {
            setError("Unable to connect to the server. Please try again.");
            return;
        }

        setLoading(true);
        let ctrl;
        let timer; 

        try {
            const payload = { repo_url: repoUrl.trim(), branch: "main" };

            ctrl = new AbortController();
            timer = setTimeout(() => ctrl.abort(), 20000);

            const res = await fetch(`${apiBase}/jobs`, {
                method: "POST",
                headers: { "content-type": "application/json" },
                body: JSON.stringify(payload),
                signal: ctrl.signal,
            });

            const isJson = res.headers.get("content-type")?.includes("application/json");
            const data = isJson ? await res.json() : null;

            if (!res.ok) {
                const msg = data?.error?.message || `Server Error (HTTP ${res.status})`;
                throw new Error(msg);
            }
            setJobId(data?.job_id || "(unknown job_id)");
        } catch (err) {
            setError(err.name === "AbortError" ? "The request took too long. Please try again later." : "Something went wrong. Please try again.");
        } finally {
            if (timer) clearTimeout(timer);
            setLoading(false);
        }
    };

    return (
        <div className="mx-auto max-w-xl p-6">
            <h1 className="text-2xl font-semibold mb-4">Submit GitHub Repository</h1>
            <form onSubmit={onSubmit} className="space-y-4">
                <label className="block">
                    <span className="block text-sm font-medium mb-1">GitHub Repo URL</span>
                    <input
                        type="url"
                        value={repoUrl}
                        onChange={(e) => setRepoUrl(e.target.value)}
                        placeholder="https://github.com/owner/repo"
                        className="w-full rounded border px-3 py-2"
                        disabled={loading}
                        required
                    />
                </label>
                <button
                    type="submit"
                    disabled={loading}
                    className={`rounded px-4 py-2 text-white ${loading ? "bg-gray-400" : "bg-blue-600 hover:bg-blue-700"}`}
                >
                    {loading ? "Submitting…" : "Submit"}
                </button>
            </form>
            {error && (
                <div className="mt-4 rounded border border-red-300 bg-red-50 p-3 text-sm text-red-700">
                    {error}
                </div>
            )}
            {jobId && (
                <div className="mt-4 rounded border border-green-300 bg-green-50 p-3 text-sm text-green-800">
                    <div className="font-medium">Job accepted</div>
                    <div className="mt-1">
                        <span className="font-mono">job_id:</span> <span className="font-mono">{jobId}</span>
                    </div>
                </div>
            )}
        </div>
    );
}