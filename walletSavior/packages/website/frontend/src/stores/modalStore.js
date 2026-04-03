import { create } from 'zustand';

const useModalStore = create((set) => ({
  activeModal: null,    // "mart" | "hotdeal" | "product" | null
  modalData: null,

  openMartModal: (product) => set({ activeModal: 'mart', modalData: product }),
  openHotdealModal: (deal) => set({ activeModal: 'hotdeal', modalData: deal }),
  openProductModal: (product) => set({ activeModal: 'product', modalData: product }),
  closeModal: () => set({ activeModal: null, modalData: null }),
}));

export default useModalStore;
