/** Entry point. Wire controls before requesting data so failure never disables navigation. */
import { bindEvents, loadDashboard } from './interactions.js';

bindEvents();
loadDashboard();
