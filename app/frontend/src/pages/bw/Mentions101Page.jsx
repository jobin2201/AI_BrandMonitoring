import React from "react";
import MentionsExplorer from "../../components/bw/MentionsExplorer";
import "./bwWorkspace.css";

export default function Mentions101Page({ sourceFilters, dateFilters }) {
  return <MentionsExplorer sourceFilters={sourceFilters} dateFilters={dateFilters} />;
}
