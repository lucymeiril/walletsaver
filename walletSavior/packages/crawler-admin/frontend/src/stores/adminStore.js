import { create } from 'zustand';
import { api } from '../api/client';
import {
  crawlers as mockCrawlers,
  crawlLogs as mockLogs,
  schedules as mockSchedules,
  plugins as mockPlugins,
  dashboardStats as mockStats,
} from '../data/mockData';

const useAdminStore = create((set, get) => ({
  // Loading / Error
  loading: false,
  error: null,

  // Crawlers
  crawlers: mockCrawlers,
  selectedCrawler: null,
  crawlerFilter: 'all',

  setCrawlerFilter: (filter) => set({ crawlerFilter: filter }),
  setSelectedCrawler: (crawler) => set({ selectedCrawler: crawler }),

  fetchCrawlers: async () => {
    set({ loading: true, error: null });
    try {
      const data = await api.getCrawlers();
      const list = Array.isArray(data) ? data : data.crawlers ?? data.data ?? [];
      if (list.length > 0) set({ crawlers: list });
    } catch {
      // API 실패 시 mock 데이터 유지
    } finally {
      set({ loading: false });
    }
  },

  runCrawler: async (id) => {
    set({ loading: true, error: null });
    try {
      const result = await api.runCrawler(id);
      return result;
    } catch (err) {
      set({ error: `크롤러 실행 실패: ${err.message}` });
      return null;
    } finally {
      set({ loading: false });
    }
  },

  toggleCrawlerStatus: (id) =>
    set((state) => ({
      crawlers: state.crawlers.map((c) =>
        c.id === id
          ? { ...c, status: c.status === 'active' ? 'inactive' : 'active' }
          : c
      ),
    })),

  getFilteredCrawlers: () => {
    const { crawlers, crawlerFilter } = get();
    if (crawlerFilter === 'all') return crawlers;
    return crawlers.filter((c) => c.category === crawlerFilter);
  },

  // Logs
  logs: mockLogs,
  logFilters: {
    crawlerName: '',
    status: 'all',
    dateFrom: '',
    dateTo: '',
  },
  logPage: 1,
  logsPerPage: 8,

  fetchLogs: async (params = {}) => {
    set({ loading: true, error: null });
    try {
      const data = await api.getLogs(params);
      const list = Array.isArray(data) ? data : data.logs ?? data.data ?? [];
      if (list.length > 0) set({ logs: list });
    } catch {
      // mock 유지
    } finally {
      set({ loading: false });
    }
  },

  setLogFilters: (filters) =>
    set((state) => ({
      logFilters: { ...state.logFilters, ...filters },
      logPage: 1,
    })),

  setLogPage: (page) => set({ logPage: page }),

  getFilteredLogs: () => {
    const { logs, logFilters } = get();
    return logs.filter((log) => {
      if (logFilters.crawlerName && !log.crawlerName.includes(logFilters.crawlerName))
        return false;
      if (logFilters.status !== 'all' && log.status !== logFilters.status)
        return false;
      return true;
    });
  },

  // Schedules
  schedules: mockSchedules,

  fetchSchedules: async () => {
    set({ loading: true, error: null });
    try {
      const data = await api.getSchedules();
      const list = Array.isArray(data) ? data : data.schedules ?? data.data ?? [];
      if (list.length > 0) set({ schedules: list });
    } catch {
      // mock 유지
    } finally {
      set({ loading: false });
    }
  },

  createSchedule: async (data) => {
    try {
      const result = await api.createSchedule(data);
      await get().fetchSchedules();
      return result;
    } catch (err) {
      set({ error: `스케줄 생성 실패: ${err.message}` });
      return null;
    }
  },

  updateScheduleApi: async (name, data) => {
    try {
      const result = await api.updateSchedule(name, data);
      await get().fetchSchedules();
      return result;
    } catch (err) {
      set({ error: `스케줄 수정 실패: ${err.message}` });
      return null;
    }
  },

  deleteScheduleApi: async (name) => {
    try {
      await api.deleteSchedule(name);
      await get().fetchSchedules();
    } catch (err) {
      set({ error: `스케줄 삭제 실패: ${err.message}` });
    }
  },

  toggleSchedule: (id) =>
    set((state) => ({
      schedules: state.schedules.map((s) =>
        s.id === id ? { ...s, enabled: !s.enabled } : s
      ),
    })),

  updateScheduleCron: (id, cron, description) =>
    set((state) => ({
      schedules: state.schedules.map((s) =>
        s.id === id ? { ...s, cron, description } : s
      ),
    })),

  // Ingestions (데이터 검토)
  ingestions: [],
  selectedIngestion: null,
  ingestionFilter: 'all',

  fetchIngestions: async (params = {}) => {
    set({ loading: true, error: null });
    try {
      const data = await api.getIngestions(params);
      const list = Array.isArray(data) ? data : data.ingestions ?? data.data ?? [];
      set({ ingestions: list });
    } catch {
      set({ ingestions: [] });
    } finally {
      set({ loading: false });
    }
  },

  fetchIngestion: async (id) => {
    set({ loading: true, error: null });
    try {
      const data = await api.getIngestion(id);
      set({ selectedIngestion: data });
      return data;
    } catch {
      set({ selectedIngestion: null });
      return null;
    } finally {
      set({ loading: false });
    }
  },

  reviewIngestion: async (id, reviewData) => {
    set({ loading: true, error: null });
    try {
      const result = await api.reviewIngestion(id, reviewData);
      await get().fetchIngestions();
      return result;
    } catch (err) {
      set({ error: `리뷰 실패: ${err.message}` });
      return null;
    } finally {
      set({ loading: false });
    }
  },

  setIngestionFilter: (filter) => set({ ingestionFilter: filter }),

  // Plugins
  plugins: mockPlugins,

  togglePlugin: (id) =>
    set((state) => ({
      plugins: state.plugins.map((p) =>
        p.id === id
          ? { ...p, status: p.status === 'active' ? 'inactive' : 'active' }
          : p
      ),
    })),

  // Dashboard
  dashboardStats: mockStats,

  fetchDashboard: async () => {
    set({ loading: true });
    try {
      const [crawlersData, logsData] = await Promise.allSettled([
        api.getCrawlers(),
        api.getLogs({}),
      ]);
      const crawlers = crawlersData.status === 'fulfilled'
        ? (Array.isArray(crawlersData.value) ? crawlersData.value : crawlersData.value.crawlers ?? crawlersData.value.data ?? [])
        : [];
      const logs = logsData.status === 'fulfilled'
        ? (Array.isArray(logsData.value) ? logsData.value : logsData.value.logs ?? logsData.value.data ?? [])
        : [];

      if (crawlers.length > 0) {
        const active = crawlers.filter(c => c.status === 'active').length;
        const successLogs = logs.filter(l => l.status === 'success').length;
        set({
          crawlers,
          logs: logs.length > 0 ? logs : get().logs,
          dashboardStats: {
            totalCrawlers: crawlers.length,
            activeCrawlers: active,
            todayCrawls: logs.length,
            successRate: logs.length > 0 ? Math.round((successLogs / logs.length) * 1000) / 10 : get().dashboardStats.successRate,
          },
        });
      }
    } catch {
      // mock 유지
    } finally {
      set({ loading: false });
    }
  },
}));

export default useAdminStore;
