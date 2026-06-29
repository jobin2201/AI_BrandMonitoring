import React from "react";
import MentionsExplorer from "../../components/bw/MentionsExplorer";
import "./bwWorkspace.css";

export default function Sources101Page({ sourceFilters, dateFilters }) {
  return (
    <MentionsExplorer
      title="Sources101"
      description="Review stored evidence by Google News, News API, Reddit, and YouTube."
      sourceFilters={sourceFilters}
      dateFilters={dateFilters}
    />
  );
}
