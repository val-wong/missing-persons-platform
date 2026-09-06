import { Routes, Route } from "react-router-dom";
import { CaseSearchPage } from "./pages/CaseSearchPage";
import { CaseDetailPage } from "./pages/CaseDetailPage";

export default function App() {
  return (
    <div className="app">
      <header className="app-header">
        <h1>Missing Persons Search</h1>
        <p className="app-subtitle">
          Public case data aggregated from authoritative sources. Currently sourced from the FBI Wanted API only.
        </p>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<CaseSearchPage />} />
          <Route path="/cases/:caseId" element={<CaseDetailPage />} />
        </Routes>
      </main>
    </div>
  );
}
