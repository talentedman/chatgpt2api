"use client";

const NAIVE_DATE_TIME_RE = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})$/;

function parseNaiveAsUtc(value: string) {
  const match = value.match(NAIVE_DATE_TIME_RE);
  if (!match) {
    return null;
  }
  const [, year, month, day, hour, minute, second] = match;
  const date = new Date(`${year}-${month}-${day}T${hour}:${minute}:${second}Z`);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function parseServerDateTime(value?: string | null) {
  const text = String(value || "").trim();
  if (!text) {
    return null;
  }

  const utcDate = parseNaiveAsUtc(text);
  if (utcDate) {
    return utcDate;
  }

  const parsed = new Date(text);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

export function formatServerDateTime(value?: string | null, fallback = "—") {
  const date = parseServerDateTime(value);
  if (!date) {
    return String(value || "").trim() || fallback;
  }

  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

