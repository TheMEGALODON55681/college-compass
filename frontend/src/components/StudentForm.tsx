import { useState, type FormEvent } from "react";
import type { BranchCategoryPref, MetaResponse, OwnershipPref, RecommendRequest } from "../types";

interface Props {
  meta: MetaResponse;
  submitting: boolean;
  onSubmit: (request: RecommendRequest) => void;
}

export default function StudentForm({ meta, submitting, onSubmit }: Props) {
  const [jeeRank, setJeeRank] = useState("");
  const [category, setCategory] = useState(meta.categories[0] ?? "OPEN");
  const [homeState, setHomeState] = useState("");
  const [prefersHomeState, setPrefersHomeState] = useState(false);
  const [branchPref, setBranchPref] = useState<BranchCategoryPref>("any");
  const [budget, setBudget] = useState("");
  const [wantsTopNirf, setWantsTopNirf] = useState(false);
  const [ownershipPref, setOwnershipPref] = useState<OwnershipPref>("both");

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    onSubmit({
      jee_rank: Number(jeeRank),
      category,
      home_state: homeState || null,
      prefers_home_state: prefersHomeState,
      preferred_branch_category: branchPref,
      budget_annual_lakhs: budget ? Number(budget) : null,
      wants_top_nirf: wantsTopNirf,
      institute_ownership_pref: ownershipPref,
    });
  }

  return (
    <form className="student-form" onSubmit={handleSubmit} aria-label="Your JEE Main profile">
      <fieldset className="form-group">
        <legend>Your rank</legend>
        <div className="field">
          <label htmlFor="jee_rank">JEE rank</label>
          <input
            id="jee_rank"
            type="number"
            inputMode="numeric"
            min={1}
            max={2000000}
            required
            value={jeeRank}
            onChange={(e) => setJeeRank(e.target.value)}
            placeholder="e.g. 45000"
          />
          <p className="hint">Overall CRL rank for OPEN. Category rank (not CRL) for EWS/OBC-NCL/SC/ST.</p>
        </div>

        <div className="field">
          <label htmlFor="category">Category</label>
          <select id="category" value={category} onChange={(e) => setCategory(e.target.value)}>
            {meta.categories.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>
      </fieldset>

      <fieldset className="form-group">
        <legend>Location</legend>
        <div className="field">
          <label htmlFor="home_state">Home state</label>
          <select id="home_state" value={homeState} onChange={(e) => setHomeState(e.target.value)}>
            <option value="">Not specified</option>
            {meta.states.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>

        <div className="field checkbox-field">
          <label>
            <input type="checkbox" checked={prefersHomeState} onChange={(e) => setPrefersHomeState(e.target.checked)} />
            Prefer colleges in my home state
          </label>
        </div>
      </fieldset>

      <fieldset className="form-group">
        <legend>What you're looking for</legend>
        <div className="field">
          <label htmlFor="branch_pref">Preferred branch type</label>
          <select id="branch_pref" value={branchPref} onChange={(e) => setBranchPref(e.target.value as BranchCategoryPref)}>
            <option value="any">Any branch</option>
            <option value="cs_adjacent">CS-adjacent (CS, IT, AI, Data Science)</option>
            <option value="core">Core engineering (Mechanical, Civil, Electrical...)</option>
          </select>
        </div>

        <div className="field">
          <label htmlFor="budget">Budget (annual fees, lakhs)</label>
          <input
            id="budget"
            type="number"
            inputMode="decimal"
            min={0}
            step={0.1}
            value={budget}
            onChange={(e) => setBudget(e.target.value)}
            placeholder="optional"
          />
        </div>

        <div className="field">
          <label htmlFor="ownership_pref">Ownership preference</label>
          <select id="ownership_pref" value={ownershipPref} onChange={(e) => setOwnershipPref(e.target.value as OwnershipPref)}>
            <option value="both">Government or PPP, no preference</option>
            <option value="government">Government only (IIT / NIT / GFTI)</option>
            <option value="ppp">PPP institutes only (IIIT)</option>
          </select>
        </div>

        <div className="field checkbox-field">
          <label>
            <input type="checkbox" checked={wantsTopNirf} onChange={(e) => setWantsTopNirf(e.target.checked)} />
            Prioritize NIRF-ranked institutes
          </label>
        </div>
      </fieldset>

      <button type="submit" disabled={submitting || !jeeRank}>
        {submitting ? "Finding colleges..." : "Find my colleges"}
      </button>
    </form>
  );
}
