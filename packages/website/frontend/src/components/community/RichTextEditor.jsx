import { useState, useRef, useCallback } from 'react';
import { useEditor, EditorContent } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import Image from '@tiptap/extension-image';
import Link from '@tiptap/extension-link';
import Placeholder from '@tiptap/extension-placeholder';
import s from './RichTextEditor.module.css';

export default function RichTextEditor({ content, onChange, placeholder }) {
  const [showLinkInput, setShowLinkInput] = useState(false);
  const [linkUrl, setLinkUrl] = useState('');
  const imgInputRef = useRef(null);

  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: { levels: [2, 3] },
      }),
      Image,
      Link.configure({ openOnClick: false }),
      Placeholder.configure({ placeholder: placeholder || '내용을 입력하세요' }),
    ],
    content: content || '',
    onUpdate: ({ editor: ed }) => {
      onChange?.(ed.getHTML());
    },
  });

  const handleImageUpload = useCallback(() => {
    imgInputRef.current?.click();
  }, []);

  const onImageFile = useCallback((e) => {
    const files = Array.from(e.target.files || []);
    files.forEach((file) => {
      const reader = new FileReader();
      reader.onload = (ev) => {
        editor?.chain().focus().setImage({ src: ev.target.result }).run();
      };
      reader.readAsDataURL(file);
    });
    e.target.value = '';
  }, [editor]);

  const applyLink = useCallback(() => {
    if (!linkUrl.trim()) {
      editor?.chain().focus().unsetLink().run();
    } else {
      const url = linkUrl.startsWith('http') ? linkUrl : `https://${linkUrl}`;
      editor?.chain().focus().extendMarkRange('link').setLink({ href: url }).run();
    }
    setShowLinkInput(false);
    setLinkUrl('');
  }, [editor, linkUrl]);

  const openLinkInput = useCallback(() => {
    const prev = editor?.getAttributes('link').href || '';
    setLinkUrl(prev);
    setShowLinkInput(true);
  }, [editor]);

  if (!editor) return null;

  const ARIA_LABELS = {
    'B': '굵게', 'I': '기울임', 'S': '취소선',
    'H2': '제목 2', 'H3': '제목 3',
    '•': '글머리 기호', '1.': '번호 매기기',
    '🔗': '링크', '📷': '이미지',
    '❝': '인용', '</>': '코드 블록', '─': '구분선',
    '↶': '실행 취소', '↷': '다시 실행',
  };

  const btn = (label, action, active) => (
    <button
      type="button"
      className={`${s.tbBtn} ${active ? s.tbBtnActive : ''}`}
      onClick={action}
      title={ARIA_LABELS[label] || label}
      aria-label={ARIA_LABELS[label] || label}
      aria-pressed={active || undefined}
    >
      {label}
    </button>
  );

  return (
    <div className={s.editorWrap}>
      <div className={s.toolbar} role="toolbar" aria-label="텍스트 서식">
        {btn('B', () => editor.chain().focus().toggleBold().run(), editor.isActive('bold'))}
        {btn('I', () => editor.chain().focus().toggleItalic().run(), editor.isActive('italic'))}
        {btn('S', () => editor.chain().focus().toggleStrike().run(), editor.isActive('strike'))}
        {btn('H2', () => editor.chain().focus().toggleHeading({ level: 2 }).run(), editor.isActive('heading', { level: 2 }))}
        {btn('H3', () => editor.chain().focus().toggleHeading({ level: 3 }).run(), editor.isActive('heading', { level: 3 }))}
        <span className={s.tbSep} />
        {btn('•', () => editor.chain().focus().toggleBulletList().run(), editor.isActive('bulletList'))}
        {btn('1.', () => editor.chain().focus().toggleOrderedList().run(), editor.isActive('orderedList'))}
        <span className={s.tbSep} />
        {btn('🔗', openLinkInput, editor.isActive('link'))}
        {btn('📷', handleImageUpload, false)}
        <span className={s.tbSep} />
        {btn('❝', () => editor.chain().focus().toggleBlockquote().run(), editor.isActive('blockquote'))}
        {btn('</>', () => editor.chain().focus().toggleCodeBlock().run(), editor.isActive('codeBlock'))}
        {btn('─', () => editor.chain().focus().setHorizontalRule().run(), false)}
        <span className={s.tbSep} />
        {btn('↶', () => editor.chain().focus().undo().run(), false)}
        {btn('↷', () => editor.chain().focus().redo().run(), false)}
      </div>

      {showLinkInput && (
        <div className={s.linkPopup}>
          <input
            value={linkUrl}
            onChange={(e) => setLinkUrl(e.target.value)}
            placeholder="URL을 입력하세요"
            onKeyDown={(e) => e.key === 'Enter' && applyLink()}
            autoFocus
          />
          <button type="button" className={s.linkApply} onClick={applyLink}>적용</button>
          <button type="button" className={s.linkCancel} onClick={() => setShowLinkInput(false)}>취소</button>
        </div>
      )}

      <div className={s.editor}>
        <EditorContent editor={editor} />
      </div>

      <input
        ref={imgInputRef}
        type="file"
        accept="image/*"
        multiple
        hidden
        onChange={onImageFile}
      />
    </div>
  );
}
