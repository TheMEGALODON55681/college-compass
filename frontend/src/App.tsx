import { useEffect } from "react";
import { BrowserRouter, Route, Routes, useLocation } from "react-router";
import { MotionConfig } from "motion/react";
import { fBody, C } from "./lib/tokens";
import { NavBar } from "./components/NavBar";
import { Landing } from "./screens/Landing";
import { RankCard } from "./screens/RankCard";
import { Results } from "./screens/Results";
import { CollegeDetail } from "./screens/CollegeDetail";
import { Counsellor } from "./screens/Counsellor";
import { Report } from "./screens/Report";

function ScrollToTop() {
  const { pathname } = useLocation();
  useEffect(() => window.scrollTo({ top: 0 }), [pathname]);
  return null;
}

export default function App() {
  return (
    <MotionConfig reducedMotion="user">
      <BrowserRouter>
        <ScrollToTop />
        <div style={{ fontFamily: fBody, background: C.paper, minHeight: "100vh" }}>
          <NavBar />
          <Routes>
            <Route path="/" element={<Landing />} />
            <Route path="/rank-card" element={<RankCard />} />
            <Route path="/shortlist" element={<Results />} />
            <Route path="/college/:id" element={<CollegeDetail />} />
            <Route path="/counsellor" element={<Counsellor />} />
            <Route path="/report" element={<Report />} />
          </Routes>
        </div>
      </BrowserRouter>
    </MotionConfig>
  );
}
