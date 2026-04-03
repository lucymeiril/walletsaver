import { create } from 'zustand';
import { api } from '../api/client';

const useAdminStore = create((set, get) => ({
  // Loading / Error
  loading: false,
  error: null,

  clearError: () => set({ error: null }),

  // Crawlers
  crawlers: [],
  selectedCrawler: null,
  crawlerFilter: 'all',

  setCrawlerFilter: (filter) => set({ crawlerFilter: filter }),
  setSelectedCrawler: (crawler) => set({ selectedCrawler: crawler }),

  fetchCrawlers: async () => {
    set({ loading: true, error: null });
    try {
      const data = await api.getCrawlers();
      const list = Array.isArray(data) ? data : data.crawlers ?? data.data ?? [];
      const mapped = list.map((c) => ({
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
      }));
      set({ crawlers: mapped });
    } catch (err) {
      set({ error: `⚠️ 서버 연결 실패: 크롤러 목록을 불러올 수 없습니다 (${err.message})` });
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

  toggleCrawlerStatus: async (id) => {
    const { crawlers } = get();
    const crawler = crawlers.find((c) => c.id === id);
    if (!crawler) return;

    const newStatus = crawler.status === 'active' ? 'inactive' : 'active';
    // 낙관적 업데이트
    set({
      crawlers: crawlers.map((c) =>
        c.id === id ? { ...c, status: newStatus } : c
      ),
    });
    try {
      await api.toggleCrawler(id, newStatus);
    } catch (err) {
      // 롤백
      set({
        crawlers: crawlers,
        error: `상태 변경 실패: ${err.message}`,
      });
    }
  },

  getFilteredCrawlers: () => {
    const { crawlers, crawlerFilter } = get();
    if (crawlerFilter === 'all') return crawlers;
    return crawlers.filter((c) => c.category === crawlerFilter);
  },

  // Logs
  logs: [],
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
      set({ logs: list });
    } catch (err) {
      set({ error: `⚠️ 서버 연결 실패: 로그를 불러올 수 없습니다 (${err.message})` });
    } finally {
      set({ loading: false });
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
      set({ error: `CSV 내보내기 실패: ${err.message}` });
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
      const name = log.crawlerName || log.job_id || '';
      if (logFilters.crawlerName && !name.includes(logFilters.crawlerName))
        return false;
      if (logFilters.status !== 'all' && log.status !== logFilters.status)
        return false;
      // 날짜 범위 필터
      const started = log.startTime || log.started_at;
      if (started && (logFilters.dateFrom || logFilters.dateTo)) {
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
      }
      return true;
    });
  },

  // Schedules
  schedules: [],

  fetchSchedules: async () => {
    set({ loading: true, error: null });
    try {
      const data = await api.getSchedules();
      const list = Array.isArray(data) ? data : data.schedules ?? data.data ?? [];
      set({ schedules: list });
    } catch (err) {
      set({ error: `⚠️ 서버 연결 실패: 스케줄을 불러올 수 없습니다 (${err.message})` });
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

  toggleSchedule: async (id) => {
    const { schedules } = get();
    const schedule = schedules.find((s) => s.id === id);
    if (!schedule) return;

    const newEnabled = !schedule.enabled;
    const crawlerName = schedule.crawlerId || schedule.crawlerName;

    // 낙관적 업데이트
    set({
      schedules: schedules.map((s) =>
        s.id === id ? { ...s, enabled: newEnabled } : s
      ),
    });

    try {
      await api.toggleSchedule(crawlerName, newEnabled);
    } catch (err) {
      // 롤백
      set({
        schedules: schedules,
        error: `스케줄 토글 실패: ${err.message}`,
      });
    }
  },

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
      const list = Array.isArray(data) ? data : data.items ?? data.ingestions ?? data.data ?? [];
      set({ ingestions: list });
    } catch (err) {
      set({ ingestions: [], error: `⚠️ 서버 연결 실패: 데이터 검토 목록을 불러올 수 없습니다 (${err.message})` });
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
  plugins: [],

  fetchPlugins: async () => {
    set({ loading: true, error: null });
    try {
      const data = await api.getPlugins();
      const list = Array.isArray(data) ? data : data.plugins ?? data.data ?? [];
      set({ plugins: list });
    } catch (err) {
      set({ error: `⚠️ 서버 연결 실패: 플러그인 목록을 불러올 수 없습니다 (${err.message})` });
    } finally {
      set({ loading: false });
    }
  },

  togglePlugin: async (id) => {
    const { plugins } = get();
    const plugin = plugins.find((p) => p.id === id);
    if (!plugin) return;

    const newStatus = plugin.status === 'active' ? 'inactive' : 'active';
    // 낙관적 업데이트
    set({
      plugins: plugins.map((p) =>
        p.id === id ? { ...p, status: newStatus } : p
      ),
    });

    try {
      await api.togglePlugin(id, newStatus);
    } catch (err) {
      // 롤백
      set({
        plugins: plugins,
        error: `플러그인 토글 실패: ${err.message}`,
      });
    }
  },

  updatePluginSettings: async (id, settings) => {
    set({ loading: true, error: null });
    try {
      await api.updatePluginSettings(id, settings);
      // 설정 변경 후 목록 새로고침
      await get().fetchPlugins();
    } catch (err) {
      set({ error: `설정 저장 실패: ${err.message}` });
    } finally {
      set({ loading: false });
    }
  },

  // Dashboard
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
    set({ loading: true, error: null });
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
      set({ error: `⚠️ 서버 연결 실패: 대시보드 데이터를 불러올 수 없습니다 (${err.message})` });
    } finally {
      set({ loading: false });
    }
  },
}));

export default useAdminStore;
