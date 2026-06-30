import React from "react";
import {
  BW_SOURCE_LABELS,
  DEFAULT_BW_WORKSPACE,
  saveCompanyWorkspace,
  setActiveCompanyName,
} from "../../../utils/bw/companyStorage";
import {
  getBwWorkspace,
  saveBwWorkspace,
} from "../../../api/bw/bwWorkspaceApi";
import "../bwWorkspace.css";

function ensureEditable(workspace) {
  return {
    ...DEFAULT_BW_WORKSPACE,
    ...workspace,
    brands: workspace.brands?.length ? workspace.brands : [""],
    products: workspace.products?.length
      ? workspace.products
      : [{ name: "", description: "" }],
    ceo: {
      name: workspace.ceo?.name || "",
      role: workspace.ceo?.role || "",
    },
    ceos: workspace.ceos?.length
      ? workspace.ceos.map(ceo => ({
        name: ceo.name || "",
        role: ceo.role || "",
      }))
      : [{
        name: workspace.ceo?.name || "",
        role: workspace.ceo?.role || "",
      }],
    executives: workspace.executives?.length
      ? workspace.executives.map(executive => (
        typeof executive === "string"
          ? { name: executive, role: "" }
          : { name: executive.name || "", role: executive.role || "" }
      ))
      : [{ name: "", role: "" }],
    campaigns: workspace.campaigns?.length ? workspace.campaigns : [""],
    hashtags: workspace.hashtags?.length ? workspace.hashtags : [""],
    keywords: workspace.keywords?.length ? workspace.keywords : [""],
  };
}

function createBlankWorkspace() {
  return ensureEditable({
    ...DEFAULT_BW_WORKSPACE,
    brands: [""],
    products: [{ name: "", description: "" }],
    ceo: { name: "", role: "" },
    ceos: [{ name: "", role: "" }],
    executives: [{ name: "", role: "" }],
    campaigns: [""],
    hashtags: [""],
    keywords: [""],
  });
}

function hasText(value) {
  return String(value || "").trim().length > 0;
}

function hasOneText(values) {
  return (values || []).some(hasText);
}

function hasOneObjectText(values, fields) {
  return (values || []).some(item => fields.some(field => hasText(item?.[field])));
}

function fieldClass(hasError) {
  return `bw-input${hasError ? " bw-field-error" : ""}`;
}

function sectionClass(hasError) {
  return `bw-section${hasError ? " bw-section-error" : ""}`;
}

function RepeatableTextList({ label, values, placeholder, onChange, error }) {
  const update = (index, value) => {
    onChange(values.map((item, itemIndex) => (itemIndex === index ? value : item)));
  };

  const remove = index => {
    const next = values.filter((_, itemIndex) => itemIndex !== index);
    onChange(next.length ? next : [""]);
  };

  return (
    <section className={sectionClass(Boolean(error))}>
      <h2 className="bw-section-title">{label}</h2>
      {error && <p className="bw-validation-message">{error}</p>}
      <p className="bw-section-copy">Add every {label.toLowerCase()} entry relevant to this workspace.</p>
      <div className="bw-repeat-list">
        {values.map((value, index) => (
          <div className="bw-repeat-row" key={`${label}-${index}`}>
            <input
              className={fieldClass(Boolean(error))}
              value={value}
              onChange={event => update(index, event.target.value)}
              placeholder={placeholder}
            />
            <button
              className="bw-icon-button"
              type="button"
              title={`Remove ${label.toLowerCase()} entry`}
              aria-label={`Remove ${label.toLowerCase()} entry`}
              onClick={() => remove(index)}
            >
              x
            </button>
          </div>
        ))}
      </div>
      <button
        className="bw-add-button"
        type="button"
        onClick={() => onChange([...values, ""])}
      >
        + Add
      </button>
    </section>
  );
}

export default function CompanySetupPage() {
  const [workspace, setWorkspace] = React.useState(createBlankWorkspace);
  const [status, setStatus] = React.useState(null);
  const [validationErrors, setValidationErrors] = React.useState({});
  const [busy, setBusy] = React.useState(false);
  const lastLookupRef = React.useRef("");
  const statusRef = React.useRef(null);
  const validationRef = React.useRef(null);

  const scrollToStatus = () => {
    window.setTimeout(() => {
      statusRef.current?.scrollIntoView({
        behavior: "smooth",
        block: "center",
      });
    }, 50);
  };

  const updateField = (field, value) => {
    setWorkspace(current => ({ ...current, [field]: value }));
    setValidationErrors(current => {
      if (!current[field]) return current;
      const next = { ...current };
      delete next[field];
      return next;
    });
    setStatus(null);
  };

  const updateCeo = (index, field, value) => {
    const ceos = workspace.ceos.map((ceo, ceoIndex) => (
      ceoIndex === index ? { ...ceo, [field]: value } : ceo
    ));
    setWorkspace(current => ({
      ...current,
      ceos,
      ceo: ceos[0] || { name: "", role: "" },
    }));
    setValidationErrors(current => {
      if (!current.ceos) return current;
      const next = { ...current };
      delete next.ceos;
      return next;
    });
    setStatus(null);
  };

  const removeCeo = index => {
    const ceos = workspace.ceos.filter((_, ceoIndex) => ceoIndex !== index);
    const next = ceos.length ? ceos : [{ name: "", role: "" }];
    setWorkspace(current => ({
      ...current,
      ceos: next,
      ceo: next[0],
    }));
    setValidationErrors(current => {
      if (!current.ceos) return current;
      const nextErrors = { ...current };
      delete nextErrors.ceos;
      return nextErrors;
    });
    setStatus(null);
  };

  const validateWorkspace = () => {
    const errors = {};
    if (!hasText(workspace.companyName)) errors.companyName = "Company name is required.";
    if (!hasText(workspace.industry)) errors.industry = "Industry is required.";
    if (!hasOneText(workspace.brands)) errors.brands = "Add at least one brand name.";
    if (!hasOneObjectText(workspace.ceos, ["name", "role"])) errors.ceos = "Add at least one CEO.";
    if (!hasOneObjectText(workspace.products, ["name", "description"])) errors.products = "Add at least one product.";
    if (!hasOneObjectText(workspace.executives, ["name", "role"])) errors.executives = "Add at least one executive.";
    if (!hasOneText(workspace.campaigns)) errors.campaigns = "Add at least one campaign.";
    if (!hasOneText(workspace.hashtags)) errors.hashtags = "Add at least one hashtag.";
    if (!hasOneText(workspace.keywords)) errors.keywords = "Add at least one keyword.";
    setValidationErrors(errors);
    if (Object.keys(errors).length) {
      setStatus({
        type: "error",
        message: "Please complete the highlighted required workspace sections before saving.",
      });
      window.setTimeout(() => {
        validationRef.current?.scrollIntoView({
          behavior: "smooth",
          block: "center",
        });
      }, 50);
      return false;
    }
    return true;
  };

  const updateProduct = (index, field, value) => {
    updateField(
      "products",
      workspace.products.map((product, productIndex) => (
        productIndex === index ? { ...product, [field]: value } : product
      )),
    );
  };

  const removeProduct = index => {
    const next = workspace.products.filter((_, productIndex) => productIndex !== index);
    updateField("products", next.length ? next : [{ name: "", description: "" }]);
  };

  const updateExecutive = (index, field, value) => {
    updateField(
      "executives",
      workspace.executives.map((executive, executiveIndex) => (
        executiveIndex === index ? { ...executive, [field]: value } : executive
      )),
    );
  };

  const removeExecutive = index => {
    const next = workspace.executives.filter((_, executiveIndex) => executiveIndex !== index);
    updateField("executives", next.length ? next : [{ name: "", role: "" }]);
  };

  const loadExistingCompany = async ({ silentNotFound = false } = {}) => {
    const companyName = workspace.companyName.trim();
    if (!companyName || busy) return;
    const lookupKey = companyName.toLocaleLowerCase();
    if (silentNotFound && lastLookupRef.current === lookupKey) return;

    setBusy(true);
    setStatus({ type: "loading", message: `Looking for ${companyName}...` });
    try {
      const saved = await getBwWorkspace(companyName);
      setWorkspace(ensureEditable(saved));
      setValidationErrors({});
      saveCompanyWorkspace(saved);
      setActiveCompanyName(saved.companyName);
      lastLookupRef.current = saved.companyName.toLocaleLowerCase();
      setStatus({
        type: "loaded",
        message: `Loaded ${saved.companyName}. You can edit and save it again.`,
        location: saved.storageLocation,
      });
    } catch (error) {
      lastLookupRef.current = lookupKey;
      if (error.status === 404) {
        if (!silentNotFound) {
          setValidationErrors({});
          setWorkspace({
            ...createBlankWorkspace(),
            companyName,
          });
        }
        setStatus(silentNotFound ? null : {
          type: "info",
          message: `No saved workspace found for ${companyName}. Continue to create it.`,
        });
        if (!silentNotFound) scrollToStatus();
      } else {
        setStatus({ type: "error", message: error.message });
      }
    } finally {
      setBusy(false);
    }
  };

  const handleSave = async event => {
    event.preventDefault();
    if (!validateWorkspace()) return;
    setBusy(true);
    setStatus({ type: "loading", message: "Saving workspace..." });
    try {
      const response = await saveBwWorkspace(workspace);
      const saved = saveCompanyWorkspace(response.workspace);
      setActiveCompanyName(saved.companyName);
      lastLookupRef.current = "";
      setValidationErrors({});
      setWorkspace(createBlankWorkspace());
      setStatus({
        type: "success",
        message: response.message,
        location: response.storage_location,
      });
    } catch (error) {
      setStatus({ type: "error", message: error.message });
    } finally {
      setBusy(false);
    }
  };

  const handleNewCompany = () => {
    setWorkspace(createBlankWorkspace());
    setValidationErrors({});
    setStatus(null);
    lastLookupRef.current = "";
  };

  return (
    <div className="bw-page">
      <div className="bw-page-header">
        <div className="bw-eyebrow">BW / Brand Workspace</div>
        <h1 className="bw-heading">Company Setup</h1>
        <p className="bw-lead">
          Configure the company, its portfolio, leadership, campaigns, and discovery terms.
        </p>
      </div>

      <form className="bw-setup-form" onSubmit={handleSave}>
        <section className={sectionClass(validationErrors.companyName || validationErrors.industry)}>
          <h2 className="bw-section-title">Company</h2>
          {(validationErrors.companyName || validationErrors.industry) && (
            <p className="bw-validation-message">
              {[validationErrors.companyName, validationErrors.industry].filter(Boolean).join(" ")}
            </p>
          )}
          <p className="bw-section-copy">Core identity for the active brand workspace.</p>
          <div className="bw-field-grid">
            <label className="bw-label">
              Company Name
              <span className="bw-company-lookup">
                <input
                  className={fieldClass(validationErrors.companyName)}
                  value={workspace.companyName}
                  onChange={event => updateField("companyName", event.target.value)}
                  onBlur={() => loadExistingCompany({ silentNotFound: true })}
                  placeholder="TCS"
                />
                <button
                  className="bw-load-button"
                  type="button"
                  onClick={() => loadExistingCompany()}
                  disabled={busy || !workspace.companyName.trim()}
                >
                  Load existing
                </button>
              </span>
            </label>
            <label className="bw-label">
              Industry
              <input
                className={fieldClass(validationErrors.industry)}
                value={workspace.industry}
                onChange={event => updateField("industry", event.target.value)}
                placeholder="Technology"
              />
            </label>
          </div>
        </section>

        <RepeatableTextList
          label="Brand Names"
          values={workspace.brands}
          placeholder="Enter brand name"
          onChange={values => updateField("brands", values)}
          error={validationErrors.brands}
        />

        <section className={sectionClass(validationErrors.ceos)}>
          <h2 className="bw-section-title">CEOs</h2>
          {validationErrors.ceos && <p className="bw-validation-message">{validationErrors.ceos}</p>}
          <p className="bw-section-copy">Add one or more chief executives and their roles.</p>
          <div className="bw-repeat-list">
            {workspace.ceos.map((ceo, index) => (
              <div className="bw-executive-row" key={`ceo-${index}`}>
                <input
                  className={fieldClass(validationErrors.ceos)}
                  value={ceo.name}
                  onChange={event => updateCeo(index, "name", event.target.value)}
                  placeholder="CEO name"
                />
                <textarea
                  className={`bw-textarea${validationErrors.ceos ? " bw-field-error" : ""}`}
                  value={ceo.role}
                  onChange={event => updateCeo(index, "role", event.target.value)}
                  placeholder="CEO role or description"
                />
                <button
                  className="bw-icon-button"
                  type="button"
                  title="Remove CEO"
                  aria-label="Remove CEO"
                  onClick={() => removeCeo(index)}
                >
                  x
                </button>
              </div>
            ))}
          </div>
          <button
            className="bw-add-button"
            type="button"
            onClick={() => updateField("ceos", [
              ...workspace.ceos,
              { name: "", role: "" },
            ])}
          >
            + Add CEO
          </button>
        </section>

        <section className={sectionClass(validationErrors.products)}>
          <h2 className="bw-section-title">Products</h2>
          {validationErrors.products && <p className="bw-validation-message">{validationErrors.products}</p>}
          <p className="bw-section-copy">Add product names with enough context for later analysis.</p>
          <div className="bw-repeat-list">
            {workspace.products.map((product, index) => (
              <div className="bw-product-row" key={`product-${index}`}>
                <input
                  className={fieldClass(validationErrors.products)}
                  value={product.name}
                  onChange={event => updateProduct(index, "name", event.target.value)}
                  placeholder="Product name"
                />
                <textarea
                  className={`bw-textarea${validationErrors.products ? " bw-field-error" : ""}`}
                  value={product.description}
                  onChange={event => updateProduct(index, "description", event.target.value)}
                  placeholder="Product description"
                />
                <button
                  className="bw-icon-button"
                  type="button"
                  title="Remove product"
                  aria-label="Remove product"
                  onClick={() => removeProduct(index)}
                >
                  x
                </button>
              </div>
            ))}
          </div>
          <button
            className="bw-add-button"
            type="button"
            onClick={() => updateField("products", [
              ...workspace.products,
              { name: "", description: "" },
            ])}
          >
            + Add product
          </button>
        </section>

        <section className={sectionClass(validationErrors.executives)}>
          <h2 className="bw-section-title">Executives</h2>
          {validationErrors.executives && <p className="bw-validation-message">{validationErrors.executives}</p>}
          <p className="bw-section-copy">
            Add each executive name and their current or former role.
          </p>
          <div className="bw-repeat-list">
            {workspace.executives.map((executive, index) => (
              <div className="bw-executive-row" key={`executive-${index}`}>
                <input
                  className={fieldClass(validationErrors.executives)}
                  value={executive.name}
                  onChange={event => updateExecutive(index, "name", event.target.value)}
                  placeholder="Executive name"
                />
                <textarea
                  className={`bw-textarea${validationErrors.executives ? " bw-field-error" : ""}`}
                  value={executive.role}
                  onChange={event => updateExecutive(index, "role", event.target.value)}
                  placeholder="Role or description"
                />
                <button
                  className="bw-icon-button"
                  type="button"
                  title="Remove executive"
                  aria-label="Remove executive"
                  onClick={() => removeExecutive(index)}
                >
                  x
                </button>
              </div>
            ))}
          </div>
          <button
            className="bw-add-button"
            type="button"
            onClick={() => updateField("executives", [
              ...workspace.executives,
              { name: "", role: "" },
            ])}
          >
            + Add executive
          </button>
        </section>
        <RepeatableTextList
          label="Campaigns"
          values={workspace.campaigns}
          placeholder="Campaign name"
          onChange={values => updateField("campaigns", values)}
          error={validationErrors.campaigns}
        />
        <RepeatableTextList
          label="Hashtags"
          values={workspace.hashtags}
          placeholder="#campaign"
          onChange={values => updateField("hashtags", values)}
          error={validationErrors.hashtags}
        />
        <RepeatableTextList
          label="Keywords"
          values={workspace.keywords}
          placeholder="Monitoring keyword"
          onChange={values => updateField("keywords", values)}
          error={validationErrors.keywords}
        />

        <section className="bw-section">
          <h2 className="bw-section-title">Configured Sources</h2>
          <p className="bw-section-copy">Select the sources associated with this workspace configuration.</p>
          <div className="bw-source-grid">
            {Object.entries(BW_SOURCE_LABELS).map(([key, label]) => (
              <label className="bw-source-option" key={key}>
                <input
                  type="checkbox"
                  checked={Boolean(workspace.sources[key])}
                  onChange={event => updateField("sources", {
                    ...workspace.sources,
                    [key]: event.target.checked,
                  })}
                />
                {label}
              </label>
            ))}
          </div>
        </section>

        <div className="bw-form-actions">
          <button className="bw-save-button" type="submit" disabled={busy}>
            {busy ? "Working..." : "Save"}
          </button>
          <button className="bw-secondary-button" type="button" onClick={handleNewCompany}>
            New company
          </button>
        </div>
        {status && (
          <div
            ref={node => {
              statusRef.current = node;
              validationRef.current = node;
            }}
            className={`bw-save-notice bw-save-notice-${status.type}`}
            role="status"
          >
            <strong>{status.message}</strong>
            {status.location && <span>CSV storage: {status.location}</span>}
          </div>
        )}
      </form>
    </div>
  );
}
