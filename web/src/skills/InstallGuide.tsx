import Modal from '../components/Modal'
import type { SkillTarget } from '../types/api'

// ChatGPT용 · Claude용 ZIP 을 내려받은 뒤 보이는 안내. EASY 는 ZIP 을 내려줄 뿐 설치하지 않는다.
const GUIDES: Record<Exclude<SkillTarget, 'source'>, { product: string; steps: string[]; note: string }> = {
  chatgpt: {
    product: 'ChatGPT',
    steps: ['ChatGPT 의 Skills 화면을 엽니다.', '만들기 → 컴퓨터에서 업로드를 누릅니다.', '내려받은 ZIP 파일을 선택합니다.'],
    note: '계정 · 워크스페이스에 따라 Skills 기능을 쓸 수 없을 수 있습니다.',
  },
  claude: {
    product: 'Claude',
    steps: ['Customize → Skills 로 갑니다.', 'Create skill → Upload a skill 을 누릅니다.', '내려받은 ZIP 파일을 선택하고, 목록에서 Skill 을 켭니다.'],
    note: '요금제 · 조직 설정에 따라 Skills 기능을 쓸 수 없을 수 있습니다.',
  },
}

export default function InstallGuide({
  target,
  filename,
  onAgain,
  onClose,
}: {
  target: Exclude<SkillTarget, 'source'>
  filename: string
  onAgain: () => void
  onClose: () => void
}) {
  const guide = GUIDES[target]
  return (
    <Modal title={`${guide.product}에 추가하기`} onClose={onClose}>
      <p className="install-file">
        <span className="install-check" aria-hidden="true">✓</span>
        <span><strong>{filename}</strong> 을 내려받았습니다.</span>
      </p>
      <p className="install-lead">아래 순서로 {guide.product} 에 직접 올리면 됩니다. EASY 가 대신 설치하지는 않습니다.</p>
      <ol className="install-steps">
        {guide.steps.map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ol>
      <p className="install-note">* {guide.note}</p>
      <div className="modal-actions">
        <button type="button" className="link-button" onClick={onAgain}>다시 내려받기</button>
        <button type="button" className="pill pill-primary" onClick={onClose} autoFocus>확인</button>
      </div>
    </Modal>
  )
}
