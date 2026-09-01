import { useApp } from "./store/AppContext.jsx";
import Header from "./components/Header.jsx";
import Dock from "./components/Dock.jsx";
import Feed from "./components/Feed.jsx";
import Explorer from "./components/Explorer.jsx";
import MapView from "./components/MapView.jsx";
import Search from "./components/Search.jsx";
import Chat from "./components/Chat.jsx";
import NoteSheet from "./components/NoteSheet.jsx";
import ContextMenu from "./components/ContextMenu.jsx";
import FolderFilter from "./components/FolderFilter.jsx";

export default function App() {
  const { state } = useApp();
  const v = state.view;
  return (
    <>
      <Header />
      <main>
        <Feed hidden={v !== "notes"} />
        <MapView hidden={v !== "map"} />
        <Explorer hidden={v !== "explorer"} />
        <Search hidden={v !== "search"} />
        <Chat hidden={v !== "chat"} />
      </main>
      <Dock />
      <NoteSheet />
      <ContextMenu />
      <FolderFilter />
    </>
  );
}
