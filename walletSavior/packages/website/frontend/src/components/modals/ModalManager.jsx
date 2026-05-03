import useModalStore from '../../stores/modalStore';
import GasStationModal from './GasStationModal';
import ProductDetailModal from '../ProductDetailModal';

export default function ModalManager() {
  const { activeModal, modalData, closeModal } = useModalStore();

  if (!activeModal) return null;

  switch (activeModal) {
    case 'mart':
    case 'hotdeal':
      return <ProductDetailModal product={modalData} onClose={closeModal} mode="preview" />;
    case 'gasStation':
      return <GasStationModal data={modalData} onClose={closeModal} />;
    case 'product':
      return <ProductDetailModal product={modalData} onClose={closeModal} />;
    case 'productDetail':
      return <ProductDetailModal product={modalData} onClose={closeModal} />;
    default:
      return null;
  }
}
