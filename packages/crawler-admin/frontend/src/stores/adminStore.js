import { create } from 'zustand';
import { api } from '../api/client';

function toUserMessage(err, fallback) {
  if (!err) return fallback;
  const status = err.status || err.statusCode;
  if (status === 502 || status === 503) return '서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.';
  if (status === 404) return '요청한 리소스를 찾을 수 없습니다.';
  if (status === 422) return '입력값이 올바르지 않습니다.';
  if (status >= 500) return '서버 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.';
  return fallback;
}

const useAdminStore = create((set, get) => ({
  crawlersLoading: false,
  crawlersError: null,
  logsLoading: false,
  logsError: null,
  schedulesLoading: false,
  schedulesError: null,
  dashboardLoading: false,
  dashboardError: null,
  ingestionsLoading: false,
  ingestionsError: null,

  clearError: () => set({
    crawlersError: null,
    logsError: null,
    schedulesError: null,
    dashboardError: null,
    ingestionsError: null,
  }),

  crawlers: [],
  selectedCrawler: null,
  crawlerFilter: 'all',
  setCrawlerFilter: (filter) => set({ crawlerFilter: filter }),
  setSelectedCrawler: (crawler) => set({ selectedCrawler: crawler }),

  fetchCrawlers: async () => {
    set({ crawlersLoading: true, crawlersError: null });
    try {
      const data = await api.getCrawlers();
      const list = Array.isArray(data) ? data : data.crawlers ?? data.data ?? [];
      set({
        crawlers: list.map((c) => ({
          id: c.name,
          name: c.display_name || c.name,
          category: c.category || 'etc',
          difficulty: c.difficulty ?? '중',
          status: c.status || 'active',
          lastCrawl: c.lastCrawl || c.last_run || '',
          successRate: c.successRate ?? c.success_rate ?? 0,
          totalRuns: c.totalRuns ?? c.total_runs ?? 0,
          description: c.description || '',
          schedule: c.schedule || '',
          recentRuns: c.recentRuns ?? c.recent_runs ?? [],
          wafBlockedCount: c.wafBlockedCount ?? c.waf_blocked_count ?? 0,
          wafBlockedItems: c.wafBlockedItems ?? c.waf_blocked_items ?? [],
        })),
      });
    } catch (err) {
      set({ crawlersError: toUserMessage(err, '크롤러 목록을 불러올 수 없습니다.') });
    } finally {
      set({ crawlersLoading: false });
    }
  },

  runCrawler: async (id) => {
    set({ crawlersLoading: true, crawlersError: null });
    try {
      return await api.runCrawler(id);
    } catch (err) {
      set({ crawlersError: toUserMessage(err, '크롤러 실행에 실패했습니다.') });
      return null;
    } finally {
      set({ crawlersLoading: false });
    }
  },

  getFilteredCrawlers: () => {
    const { crawlers, crawlerFilter } = get();
    return crawlerFilter === 'all' ? crawlers : crawlers.filter((c) => c.category === crawlerFilter);
  },

  logs: [],
  logFilters: { crawlerName: '', status: 'all', dateFrom: '', dateTo: '' },
  logPage: 1,
  logsPerPage: 8,

  fetchLogs: async (params = {}) => {
    set({ logsLoading: true, logsError: null });
    try {
      const data = await api.getLogs(params);
      set({ logs: Array.isArray(data) ? data : data.logs ?? data.data ?? [] });
    } catch (err) {
      set({ logsError: toUserMessage(err, '로그를 불러올 수 없습니다.') });
    } finally {
      set({ logsLoading: false });
    }
  },

  exportLogs: async (params = {}) => {
    try {
      const blob = await api.exportLogsCsv(params);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'crawl_logs.csv';
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      set({ logsError: toUserMessage(err, 'CSV 내보내기에 실패했습니다.') });
    }
  },

  setLogFilters: (filters) => set((state) => ({
    logFilters: { ...state.logFilters, ...filters },
    logPage: 1,
  })),
  setLogPage: (page) => set({ logPage: page }),

  getFilteredLogs: () => {
    const { logs, logFilters } = get();
    return logs.filter((log) => {
      const name = log.crawlerName || log.job_id || '';
      if (logFilters.crawlerName && !name.includes(logFilters.crawlerName)) return false;
      if (logFilters.status !== 'all' && log.status !== logFilters.status) return false;
      const started = log.startTime || log.started_at;
      if (!started || (!logFilters.dateFrom && !logFilters.dateTo)) return true;
      const ts = new Date(started);
      if (isNaN(ts.getTime())) return false;
      if (logFilters.dateFrom) {
        const from = new Date(logFilters.dateFrom);
        from.setHours(0, 0, 0, 0);
        if (ts < from) return false;
      }
      if (logFilters.dateTo) {
        const to = new Date(logFilters.dateTo);
        to.setHours(23, 59, 59, 999);
        if (ts > to) return false;
      }
      return true;
    });
  },

  schedules: [],

  fetchSchedules: async () => {
    set({ schedulesLoading: true, schedulesError: null });
    try {
      const data = await api.getSchedules();
      set({ schedules: Array.isArray(data) ? data : data.schedules ?? data.data ?? [] });
    } catch (err) {
      set({ schedulesError: toUserMessage(err, '스케줄을 불러올 수 없습니다.') });
    } finally {
      set({ schedulesLoading: false });
    }
  },

  createSchedule: async (data) => {
    try {
      const result = await api.createSchedule(data);
      await get().fetchSchedules();
      return result;
    } catch (err) {
      set({ schedulesError: toUserMessage(err, '스케줄 생성에 실패했습니다.') });
      return null;
    }
  },

  updateScheduleApi: async (identifier, data) => {
    try {
      const result = await api.updateSchedule(identifier, data);
      await get().fetchSchedules();
      return result;
    } catch (err) {
      set({ schedulesError: toUserMessage(err, '스케줄 수정에 실패했습니다.') });
      return null;
    }
  },

  deleteScheduleApi: async (identifier) => {
    try {
      await api.deleteSchedule(identifier);
      await get().fetchSchedules();
    } catch (err) {
      set({ schedulesError: toUserMessage(err, '스케줄 삭제에 실패했습니다.') });
    }
  },

  toggleSchedule: async (id) => {
    const { schedules } = get();
    const schedule = schedules.find((s) => s.id === id);
    if (!schedule) return;
    const newEnabled = !schedule.enabled;
    set({ schedules: schedules.map((s) => s.id === id ? { ...s, enabled: newEnabled } : s) });
    try {
      await api.toggleSchedule(id, newEnabled);
    } catch (err) {
      set({ schedules, schedulesError: toUserMessage(err, '스케줄 토글에 실패했습니다.') });
    }
  },

  updateScheduleCron: (id, cron, description) => set((state) => ({
    schedules: state.schedules.map((s) => s.id === id ? { ...s, cron, description } : s),
  })),

  ingestions: [],
  selectedIngestion: null,
  ingestionFilter: 'all',

  fetchIngestions: async (params = {}) => {
    set({ ingestionsLoading: true, ingestionsError: null });
    try {
      const data = await api.getIngestions(params);
      set({ ingestions: Array.isArray(data) ? data : data.items ?? data.ingestions ?? data.data ?? [] });
    } catch (err) {
      set({ ingestions: [], ingestionsError: toUserMessage(err, '데이터 검토 목록을 불러올 수 없습니다.') });
    } finally {
      set({ ingestionsLoading: false });
    }
  },

  fetchIngestion: async (id) => {
    set({ ingestionsLoading: true, ingestionsError: null });
    try {
      const data = await api.getIngestion(id);
      set({ selectedIngestion: data });
      return data;
    } catch {
      set({ selectedIngestion: null });
      return null;
    } finally {
      set({ ingestionsLoading: false });
    }
  },

  reviewIngestion: async (id, reviewData) => {
    set({ ingestionsLoading: true, ingestionsError: null });
    try {
      const result = await api.reviewIngestion(id, reviewData);
      await get().fetchIngestions();
      return result;
    } catch (err) {
      set({ ingestionsError: toUserMessage(err, '리뷰 처리에 실패했습니다.') });
      return null;
    } finally {
      set({ ingestionsLoading: false });
    }
  },

  cleanupIngestions: async (cleanupData) => {
    set({ ingestionsLoading: true, ingestionsError: null });
    try {
      const result = await api.cleanupIngestions(cleanupData);
      await get().fetchIngestions();
      return result;
    } catch (err) {
      set({ ingestionsError: toUserMessage(err, '정리 작업에 실패했습니다.') });
      return null;
    } finally {
      set({ ingestionsLoading: false });
    }
  },

  deleteIngestion: async (id) => {
    set({ ingestionsLoading: true, ingestionsError: null });
    try {
      const result = await api.deleteIngestion(id);
      await get().fetchIngestions();
      return result;
    } catch (err) {
      set({ ingestionsError: toUserMessage(err, '항목 삭제에 실패했습니다.') });
      return null;
    } finally {
      set({ ingestionsLoading: false });
    }
  },

  setIngestionFilter: (filter) => set({ ingestionFilter: filter }),

  dashboardStats: {
    totalCrawlers: 0,
    activeCrawlers: 0,
    todayCrawls: 0,
    successRate: 0,
    statusDistribution: { success: 0, failure: 0, partial: 0 },
    errorTrend: [],
    alerts: [],
    crawlerCards: [],
    freshness: [],
  },
  errorTrendDays: 7,
  lastRefreshed: null,
  setErrorTrendDays: (days) => set({ errorTrendDays: days }),

  fetchDashboard: async (days) => {
    const d = days ?? get().errorTrendDays;
    set({ dashboardLoading: true, dashboardError: null });
    try {
      const stats = await api.getDashboardStats({ days: d });
      set({
        dashboardStats: {
          totalCrawlers: stats.totalCrawlers ?? 0,
          activeCrawlers: stats.activeCrawlers ?? 0,
          todayCrawls: stats.todayCrawls ?? 0,
          successRate: stats.successRate ?? 0,
          statusDistribution: stats.statusDistribution ?? { success: 0, failure: 0, partial: 0 },
          errorTrend: stats.errorTrend ?? [],
          alerts: stats.alerts ?? [],
          crawlerCards: stats.crawlerCards ?? [],
          freshness: stats.freshness ?? [],
        },
        lastRefreshed: new Date().toISOString(),
      });
    } catch (err) {
      set({ dashboardError: toUserMessage(err, '대시보드 데이터를 불러올 수 없습니다.') });
    } finally {
      set({ dashboardLoading: false });
    }
  },
}));

export default useAdminStore;
