import { useQuery } from "@tanstack/react-query";
import { fetchJSON } from "./client";
import type { Overview, ActionsSection, LBrainSection, MemoryDetail, AuditResponse } from "./types";

export const overviewQueryKey = ["overview"] as const;
export const lbrainQueryKey = ["lbrain"] as const;
export const memoryQueryKey = ["memory"] as const;
export const actionsQueryKey = ["actions"] as const;
export const auditQueryKey = ["audit"] as const;

export function useOverview() {
  return useQuery({
    queryKey: overviewQueryKey,
    queryFn: () => fetchJSON<Overview>("/api/overview"),
    refetchInterval: 30_000,
    staleTime: 10_000,
  });
}

export function useLBrain() {
  return useQuery({
    queryKey: lbrainQueryKey,
    queryFn: () => fetchJSON<LBrainSection>("/api/lbrain"),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
}

export function useMemory() {
  return useQuery({
    queryKey: memoryQueryKey,
    queryFn: () => fetchJSON<MemoryDetail>("/api/memory?limit=100"),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
}

export function useActions() {
  return useQuery({
    queryKey: actionsQueryKey,
    queryFn: () => fetchJSON<ActionsSection>("/api/actions"),
    staleTime: Infinity,
  });
}

export function useAudit() {
  return useQuery({
    queryKey: auditQueryKey,
    queryFn: () => fetchJSON<AuditResponse>("/api/actions/audit?limit=50"),
    refetchInterval: 15_000,
    staleTime: 5_000,
  });
}
