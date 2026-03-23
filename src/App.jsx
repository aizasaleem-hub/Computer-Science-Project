import { startTransition, useEffect, useState } from "react";

const TOKEN_KEY = "report-reviewer-token";

const initialAuthForm = {
  username: "",
  email: "",
  password: ""
};

const initialComposer = {
  report: "",
  file: null
};

function sortMessages(messages) {
  return [...messages].sort((left, right) => {
    if (left.created_at === right.created_at) {
      return left.id - right.id;
    }
    return left.created_at.localeCompare(right.created_at);
  });
}

function parseMessageContent(message) {
  if (message.kind === "analysis_response") {
    try {
      const parsed = JSON.parse(message.content);
      return {
        headline: parsed.overview,
        body: parsed.normalized_report,
        weaknesses: parsed.weaknesses || []
      };
    } catch (_error) {
      return { body: message.content, weaknesses: [] };
    }
  }

  if (message.kind === "refine_request") {
    try {
      const parsed = JSON.parse(message.content);
      return {
        body: parsed.report,
        selectedChanges: parsed.selected_changes || []
      };
    } catch (_error) {
      return { body: message.content };
    }
  }

  return { body: message.content };
}

function App() {
  const [token, setToken] = useState(() => window.localStorage.getItem(TOKEN_KEY) || "");
  const [authMode, setAuthMode] = useState("login");
  const [authForm, setAuthForm] = useState(initialAuthForm);
  const [authStatus, setAuthStatus] = useState("");
  const [user, setUser] = useState(null);
  const [composer, setComposer] = useState(initialComposer);
  const [conversations, setConversations] = useState([]);
  const [activeConversationId, setActiveConversationId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [analysis, setAnalysis] = useState(null);
  const [selectedIds, setSelectedIds] = useState([]);
  const [resultText, setResultText] = useState("");
  const [loading, setLoading] = useState({
    auth: false,
    analyze: false,
    refine: false,
    history: false,
    detail: false
  });

  async function apiFetch(path, options = {}) {
    const headers = new Headers(options.headers || {});
    if (token) {
      headers.set("Authorization", `Bearer ${token}`);
    }

    const response = await fetch(path, { ...options, headers });
    if (response.status === 204) {
      return null;
    }

    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.detail || "Request failed.");
    }
    return data;
  }

  async function loadCurrentUser() {
    if (!token) {
      setUser(null);
      return;
    }

    try {
      const currentUser = await apiFetch("/auth/me");
      setUser(currentUser);
    } catch (error) {
      window.localStorage.removeItem(TOKEN_KEY);
      setToken("");
      setUser(null);
      setAuthStatus(error.message);
    }
  }

  async function loadConversations() {
    if (!token) {
      setConversations([]);
      return;
    }

    setLoading((current) => ({ ...current, history: true }));
    try {
      const data = await apiFetch("/conversations");
      startTransition(() => {
        setConversations(data);
        if (!activeConversationId && data.length > 0) {
          setActiveConversationId(data[0].id);
        }
      });
    } catch (error) {
      setAuthStatus(error.message);
    } finally {
      setLoading((current) => ({ ...current, history: false }));
    }
  }

  async function loadConversationDetail(conversationId) {
    if (!conversationId || !token) {
      return;
    }

    setLoading((current) => ({ ...current, detail: true }));
    try {
      const data = await apiFetch(`/conversations/${conversationId}`);
      setMessages(sortMessages(data.messages));

      const latestAnalysis = [...data.messages]
        .reverse()
        .find((message) => message.kind === "analysis_response");
      const latestRefine = [...data.messages]
        .reverse()
        .find((message) => message.kind === "refine_response");

      if (latestAnalysis) {
        const parsedAnalysis = parseMessageContent(latestAnalysis);
        setAnalysis({
          conversation_id: conversationId,
          overview: parsedAnalysis.headline || "",
          normalized_report: parsedAnalysis.body || "",
          weaknesses: parsedAnalysis.weaknesses || []
        });
        setSelectedIds((parsedAnalysis.weaknesses || []).map((item) => item.id));
      } else {
        setAnalysis(null);
        setSelectedIds([]);
      }

      setResultText(latestRefine ? parseMessageContent(latestRefine).body || latestRefine.content : "");
    } catch (error) {
      setAuthStatus(error.message);
    } finally {
      setLoading((current) => ({ ...current, detail: false }));
    }
  }

  useEffect(() => {
    void loadCurrentUser();
  }, [token]);

  useEffect(() => {
    if (user) {
      void loadConversations();
    }
  }, [user]);

  useEffect(() => {
    if (activeConversationId) {
      void loadConversationDetail(activeConversationId);
    }
  }, [activeConversationId]);

  function updateAuthField(field, value) {
    setAuthForm((current) => ({ ...current, [field]: value }));
  }

  function updateComposerField(field, value) {
    setComposer((current) => ({ ...current, [field]: value }));
  }

  async function submitAuth(event) {
    event.preventDefault();
    setLoading((current) => ({ ...current, auth: true }));
    setAuthStatus("");

    try {
      if (authMode === "signup") {
        await apiFetch("/auth/signup", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(authForm)
        });
        setAuthMode("login");
        setAuthStatus("Account created. Log in to enter legalrunner.");
      } else {
        const data = await apiFetch("/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            username_or_email: authForm.email || authForm.username,
            password: authForm.password
          })
        });
        window.localStorage.setItem(TOKEN_KEY, data.access_token);
        setToken(data.access_token);
        setAuthForm(initialAuthForm);
      }
    } catch (error) {
      setAuthStatus(error.message);
    } finally {
      setLoading((current) => ({ ...current, auth: false }));
    }
  }

  async function analyzeReport() {
    if (!composer.report.trim() && !composer.file) {
      setAuthStatus("Provide text or upload a file first.");
      return;
    }

    setLoading((current) => ({ ...current, analyze: true }));
    setAuthStatus("");

    const formData = new FormData();
    if (composer.report.trim()) {
      formData.append("report", composer.report.trim());
    }
    if (composer.file) {
      formData.append("file", composer.file);
    }
    if (activeConversationId) {
      formData.append("conversation_id", String(activeConversationId));
    }

    try {
      const data = await apiFetch("/analyze", {
        method: "POST",
        body: formData
      });
      setAnalysis(data);
      setSelectedIds((data.weaknesses || []).map((item) => item.id));
      setResultText("");
      setComposer((current) => ({ ...current, file: null }));
      setActiveConversationId(data.conversation_id);
      await loadConversations();
      await loadConversationDetail(data.conversation_id);
    } catch (error) {
      setAuthStatus(error.message);
    } finally {
      setLoading((current) => ({ ...current, analyze: false }));
    }
  }

  async function refineReport() {
    if (!analysis) {
      return;
    }

    const selectedChanges = (analysis.weaknesses || []).filter((item) => selectedIds.includes(item.id));
    if (selectedChanges.length === 0) {
      setAuthStatus("Select at least one suggestion.");
      return;
    }

    setLoading((current) => ({ ...current, refine: true }));
    setAuthStatus("");

    try {
      const data = await apiFetch("/refine", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          conversation_id: analysis.conversation_id || activeConversationId,
          report: analysis.normalized_report,
          selected_changes: selectedChanges
        })
      });
      setResultText(data.refined_report);
      setActiveConversationId(data.conversation_id);
      await loadConversations();
      await loadConversationDetail(data.conversation_id);
    } catch (error) {
      setAuthStatus(error.message);
    } finally {
      setLoading((current) => ({ ...current, refine: false }));
    }
  }

  async function startNewConversation() {
    try {
      const conversation = await apiFetch("/conversations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: "New thread" })
      });
      setActiveConversationId(conversation.id);
      setMessages([]);
      setAnalysis(null);
      setSelectedIds([]);
      setResultText("");
      setComposer(initialComposer);
      await loadConversations();
    } catch (error) {
      setAuthStatus(error.message);
    }
  }

  function logout() {
    window.localStorage.removeItem(TOKEN_KEY);
    setToken("");
    setUser(null);
    setConversations([]);
    setActiveConversationId(null);
    setMessages([]);
    setAnalysis(null);
    setSelectedIds([]);
    setResultText("");
    setComposer(initialComposer);
  }

  function toggleSelection(weaknessId) {
    setSelectedIds((current) =>
      current.includes(weaknessId) ? current.filter((id) => id !== weaknessId) : [...current, weaknessId]
    );
  }

  if (!user) {
    return (
      <div className="auth-shell">
        <div className="auth-stage">
          <div className="auth-copy">
            <p className="brand-tag auth-brand-only">legalrunner</p>
          </div>

          <form className="auth-card" onSubmit={submitAuth}>
            <div className="auth-topline">
              <div>
                <p className="mini-label">welcome</p>
                <h2>{authMode === "login" ? "Sign in" : "Create account"}</h2>
              </div>
              <div className="auth-tabs">
                <button
                  type="button"
                  className={authMode === "login" ? "auth-tab active" : "auth-tab"}
                  onClick={() => setAuthMode("login")}
                >
                  Login
                </button>
                <button
                  type="button"
                  className={authMode === "signup" ? "auth-tab active" : "auth-tab"}
                  onClick={() => setAuthMode("signup")}
                >
                  Signup
                </button>
              </div>
            </div>

            <label>
              Username
              <input
                value={authForm.username}
                onChange={(event) => updateAuthField("username", event.target.value)}
                placeholder="aiza"
              />
            </label>

            <label>
              {authMode === "signup" ? "Email" : "Email or username"}
              <input
                type={authMode === "signup" ? "email" : "text"}
                value={authForm.email}
                onChange={(event) => updateAuthField("email", event.target.value)}
                placeholder={authMode === "signup" ? "name@example.com" : "name@example.com"}
              />
            </label>

            <label>
              Password
              <input
                type="password"
                value={authForm.password}
                onChange={(event) => updateAuthField("password", event.target.value)}
                placeholder="Enter password"
              />
            </label>

            <button type="submit" className="launch-button" disabled={loading.auth}>
              {loading.auth ? "Working..." : authMode === "login" ? "Enter legalrunner" : "Create account"}
            </button>
            {authStatus ? <p className="auth-status">{authStatus}</p> : null}
          </form>
        </div>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <aside className="memory-rail">
        <div className="memory-brand minimal">
          <p className="brand-tag compact">legalrunner</p>
        </div>

        <div className="memory-list">
          {loading.history ? <p className="empty-copy">Loading threads...</p> : null}
          {!loading.history && conversations.length === 0 ? (
            <p className="empty-copy">No saved memory yet.</p>
          ) : null}
          {conversations.map((conversation) => (
            <button
              type="button"
              key={conversation.id}
              className={conversation.id === activeConversationId ? "memory-item active" : "memory-item"}
              onClick={() => setActiveConversationId(conversation.id)}
            >
              <strong>{conversation.title}</strong>
              <span>{new Date(conversation.updated_at).toLocaleString()}</span>
            </button>
          ))}
        </div>
      </aside>

      <main className="main-stage">
        <section className="composer-panel">
          <div className="section-head">
            <h2>Place report</h2>
          </div>
          <textarea
            value={composer.report}
            onChange={(event) => updateComposerField("report", event.target.value)}
            placeholder="Paste your draft here, or pair it with an uploaded file."
          />
          <div className="composer-actions">
            <label className="upload-badge">
              <input
                type="file"
                accept=".txt,.doc,.docx,.pdf"
                onChange={(event) => updateComposerField("file", event.target.files?.[0] || null)}
              />
              <span>{composer.file ? composer.file.name : "Add file"}</span>
            </label>
            <button type="button" className="analyze-button" onClick={analyzeReport} disabled={loading.analyze}>
              {loading.analyze ? "Analyzing..." : "Analyze"}
            </button>
          </div>
          {authStatus ? <p className="inline-status">{authStatus}</p> : null}
        </section>

        <div className="content-grid">
          <section className="content-card">
            <div className="section-head">
              <h2>Suggestions</h2>
            </div>
            {analysis ? <p className="overview-pill">{analysis.overview}</p> : <p className="empty-copy">Run analysis to see suggested edits.</p>}
            <div className="suggestion-list">
              {(analysis?.weaknesses || []).map((weakness) => (
                <label key={weakness.id} className="suggestion-card">
                  <div className="suggestion-head">
                    <input
                      type="checkbox"
                      checked={selectedIds.includes(weakness.id)}
                      onChange={() => toggleSelection(weakness.id)}
                    />
                    <div>
                      <strong>{weakness.issue}</strong>
                      <span>{weakness.id}</span>
                    </div>
                  </div>
                  <p>{weakness.why_it_matters}</p>
                  <p>{weakness.suggestion}</p>
                  <small>{weakness.citation || "Context gap"}</small>
                </label>
              ))}
            </div>
          </section>

          <section className="content-card refined-card">
            <div className="section-head">
              <h2>Create refined report</h2>
              <button type="button" className="ghost-button strong" onClick={refineReport} disabled={!analysis || loading.refine}>
                {loading.refine ? "Refining..." : "Create refined report"}
              </button>
            </div>
            <pre>{resultText || "Your refined version will appear here after you choose the suggestions to apply."}</pre>
          </section>
        </div>
      </main>
    </div>
  );
}

export default App;
