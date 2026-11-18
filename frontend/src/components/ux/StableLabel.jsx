import { Children, isValidElement } from 'react';
import './StateMotion.css';

function labelText(value) {
  return Children.toArray(value).map(child => isValidElement(child) ? labelText(child.props.children) : String(child)).join('');
}
// Generated, aria-hidden sizing text keeps the real DOM label and audit text unchanged.
export default function StableLabel({ children, variants = [] }) {
  return <span className="iris-stable-label">
    {variants.map((variant, index) => <span className="iris-label-reserve" aria-hidden="true" data-label={labelText(variant)} key={index}/>)}
    <span className="iris-label-current">{children}</span>
  </span>;
}
