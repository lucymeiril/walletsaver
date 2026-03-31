import { create } from 'zustand';
import {
  crawlers as mockCrawlers,
  crawlLogs as mockLogs,
  schedules as mockSchedules,
  plugins as mockPlugins,
  dashboardStats as mockStats,
} from '../data/mockData';

const useAdminStore = create((set, get) => ({
  // Crawlers
  crawlers: mockCrawlers,
  selectedCrawler: null,
  crawlerFilter: 'all',

  setCrawlerFilter: (filter) => set({ crawlerFilter: filter }),
  setSelectedCrawler: (crawler) => set({ selectedCrawler: crawler }),

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
}));

export default useAdminStore;
