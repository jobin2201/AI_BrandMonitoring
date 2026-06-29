import React from "react";

export default function ProductPerformanceChart({ products }) {
  const maximum = Math.max(...products.map(product => product.mentions), 1);

  return (
    <section className="bw-dashboard-panel">
      <div className="bw-panel-heading">
        <div>
          <h2>Product Performance</h2>
          <p>Mentions by configured product</p>
        </div>
      </div>
      <div className="bw-product-bars">
        {products.map((product, index) => (
          <div className="bw-product-bar-row" key={product.name}>
            <div className="bw-product-bar-meta">
              <span>{product.name}</span>
              <strong>{product.mentions}</strong>
            </div>
            <div className="bw-product-bar-track">
              <div
                className="bw-product-bar-fill"
                style={{
                  width: `${Math.max(8, (product.mentions / maximum) * 100)}%`,
                  animationDelay: `${index * 70}ms`,
                }}
              />
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
