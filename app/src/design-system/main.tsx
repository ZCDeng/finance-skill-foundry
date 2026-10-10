import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { DesignSystem } from './DesignSystem.js';
// The ui primitives lean on these two for their fnd-* classes (combobox, calendar, disclosure).
import '../components/components.css';
import '../components/financial-controls.css';
import './design-system.css';

const host = document.getElementById('root');
if (!host) throw new Error('no #root to mount into');
createRoot(host).render(
  <StrictMode>
    <DesignSystem />
  </StrictMode>,
);
