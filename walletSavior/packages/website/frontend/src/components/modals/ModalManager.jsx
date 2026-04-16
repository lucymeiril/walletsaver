import useModalStore from '../../stores/modalStore';
import MartProductModal from './MartProductModal';
import HotdealModal from './HotdealModal';
import ProductQuickView from './ProductQuickView';
import ProductDetailModal from '../ProductDetailModal';

export default function ModalManager() {
  const { activeModal, modalData, closeModal } = useModalStore();

  if (!activeModal) return null;

  switch (activeModal) {
    case 'mart':
      return <MartProductModal data={modalData} onClose={closeModal} />;
    case 'hotdeal':
      return <HotdealModal data={modalData} onClose={closeModal} />;
    case 'product':
      return <ProductDetailModal product={modalData} onClose={closeModal} />;
    case 'productDetail':
      return <ProductDetailModal product={modalData} onClose={closeModal} />;
    default:
      return null;
  }
}
