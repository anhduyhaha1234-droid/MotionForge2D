/**
 * MF-END-25 (C25) — shot-anchors barrel.
 *
 * The board is mounted by the project page (the app's journey surface), so a
 * user builds/reviews anchors with the SAME project context they are looking
 * at — never through a shell, SQL or a cross-project screen.
 */
export { ShotAnchorBoard, type ShotAnchorBoardProps } from "./ShotAnchorBoard";
export {
  getConfigAnchorEvidence,
  getReskinConfigById,
  listProjectReskinConfigs,
  listVideoSegments,
  updateConfigAnchor,
  type ShotAnchorConfig,
  type ShotAnchorConfigList,
  type ShotSegment,
  type ShotSegmentList,
} from "./shotAnchorsApi";
export {
  ANCHOR_GATE_COPY,
  anchorCoverage,
  anchorGateMessage,
  anchorOverlayStyle,
  buildAnchorEdit,
  buildShotAnchors,
  classifyAnchorError,
  parseAnchor,
  projectScopeMatches,
  sourceFrameUrl,
  validateAnchor,
  type AnchorCoverage,
  type AnchorEditPlan,
  type AnchorErrorCopy,
  type AnchorEvidenceRow,
  type AnchorPoint,
  type ShotAnchor,
} from "./shotAnchorsLogic";
