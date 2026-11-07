"use client";
import { useEffect, useState } from "react";

/** The reviewer's name, remembered in this browser for the audit trail. */
export function useReviewer(): [string, (v: string) => void] {
  const [name, setName] = useState("");
  useEffect(() => {
    try { setName(localStorage.getItem("reviewer") ?? ""); } catch { /* storage unavailable */ }
  }, []);
  const set = (v: string) => {
    setName(v);
    try { localStorage.setItem("reviewer", v); } catch { /* ignore */ }
  };
  return [name, set];
}
