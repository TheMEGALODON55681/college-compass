import { useState } from "react";
import { ArrowLeft, Menu, X } from "lucide-react";
import { Link, useLocation, useNavigate } from "react-router";
import { C, fBody, fDisplay } from "../lib/tokens";
import { useWidth } from "../lib/useWidth";

export function NavBar() {
  const [open, setOpen] = useState(false);
  const w = useWidth();
  const mobile = w < 768;
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const isLanding = pathname === "/";
  const isCounsellor = pathname === "/counsellor";

  return (
    <nav style={{
      position: "sticky", top: 0, zIndex: 100,
      background: "rgba(251,250,246,0.94)", backdropFilter: "blur(14px)",
      borderBottom: `1px solid ${C.line}`,
    }}>
      <div style={{
        maxWidth: 1160, margin: "0 auto", padding: "0 24px",
        height: 64, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {!isLanding && (
            <button onClick={() => navigate(-1)} style={{
              background: "none", border: "none", cursor: "pointer",
              padding: "8px 10px 8px 0", color: C.ink500, display: "flex", alignItems: "center",
              minHeight: 44, minWidth: 44,
            }}>
              <ArrowLeft size={18} />
            </button>
          )}
          <Link to="/" style={{ textDecoration: "none" }}>
            <div style={{ fontFamily: fDisplay, fontWeight: 600, fontSize: 18, color: C.ink900, letterSpacing: "-0.01em" }}>
              College<span style={{ color: C.primary }}>Compass</span>
            </div>
          </Link>
        </div>

        {!mobile ? (
          <div style={{ display: "flex", alignItems: "center", gap: 28 }}>
            {isLanding && (
              <>
                <a href="#how" style={{ fontFamily: fBody, fontSize: 14, color: C.ink500, textDecoration: "none" }}>How it works</a>
                <a href="#preview" style={{ fontFamily: fBody, fontSize: 14, color: C.ink500, textDecoration: "none" }}>Colleges</a>
              </>
            )}
            {!isLanding && !isCounsellor && (
              <button onClick={() => navigate("/counsellor")} style={{ fontFamily: fBody, fontSize: 14, color: C.ink500, background: "none", border: "none", cursor: "pointer" }}>
                Counsellor
              </button>
            )}
            <button onClick={() => navigate("/rank-card")} style={{
              fontFamily: fBody, fontSize: 14, fontWeight: 600,
              color: "#fff", background: C.primary, border: "none",
              borderRadius: 10, padding: "10px 22px", cursor: "pointer",
              minHeight: 44,
            }}>
              Find my colleges
            </button>
          </div>
        ) : (
          <button onClick={() => setOpen(!open)} style={{
            background: "none", border: "none", cursor: "pointer", color: C.ink700,
            display: "flex", alignItems: "center", minWidth: 44, minHeight: 44, justifyContent: "center",
          }}>
            {open ? <X size={22} /> : <Menu size={22} />}
          </button>
        )}
      </div>

      {mobile && open && (
        <div style={{
          background: C.surface, borderTop: `1px solid ${C.line}`,
          padding: "16px 24px 24px", display: "flex", flexDirection: "column", gap: 12,
        }}>
          {isLanding && (
            <>
              <a href="#how" style={{ fontFamily: fBody, fontSize: 16, color: C.ink700, textDecoration: "none", display: "flex", alignItems: "center", minHeight: 44 }} onClick={() => setOpen(false)}>How it works</a>
              <a href="#preview" style={{ fontFamily: fBody, fontSize: 16, color: C.ink700, textDecoration: "none", display: "flex", alignItems: "center", minHeight: 44 }} onClick={() => setOpen(false)}>Colleges</a>
            </>
          )}
          {!isCounsellor && (
            <button onClick={() => { navigate("/counsellor"); setOpen(false); }} style={{
              fontFamily: fBody, fontSize: 16, color: C.ink700, background: "none", border: "none",
              cursor: "pointer", textAlign: "left", padding: "8px 0", minHeight: 44,
            }}>
              Counsellor
            </button>
          )}
          <button onClick={() => { navigate("/rank-card"); setOpen(false); }} style={{
            fontFamily: fBody, fontSize: 16, fontWeight: 600,
            color: "#fff", background: C.primary, border: "none",
            borderRadius: 10, padding: "14px 20px", cursor: "pointer", textAlign: "left", minHeight: 44,
          }}>
            Find my colleges
          </button>
        </div>
      )}
    </nav>
  );
}
