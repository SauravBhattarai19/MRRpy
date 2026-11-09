import type { MDXComponents } from 'mdx/types';
import DEMFlowWidget    from './src/components/dem/DEMFlowWidget';
import DEM3DWidget      from './src/components/dem/DEM3DWidget';
import FlowAccumWidget  from './src/components/dem/FlowAccumWidget';
import PitFillWidget    from './src/components/dem/PitFillWidget';
import SlopeCalcWidget  from './src/components/dem/SlopeCalcWidget';
import FlowDirTeachWidget from './src/components/dem/FlowDirTeachWidget';
import PitTeachWidget   from './src/components/dem/PitTeachWidget';
import TopoAccumWidget  from './src/components/dem/TopoAccumWidget';
import WatershedConceptWidget from './src/components/watershed/WatershedConceptWidget';
import BFSDelineateWidget     from './src/components/watershed/BFSDelineateWidget';
import CatchmentMapWidget     from './src/components/watershed/CatchmentMapWidget';
import WatershedExploreWidget from './src/components/watershed/WatershedExploreWidget';
import SaintVenantWidget      from './src/components/routing/SaintVenantWidget';
import ManningCelerityWidget  from './src/components/routing/ManningCelerityWidget';
import FiniteDiffBuildupWidget from './src/components/routing/FiniteDiffBuildupWidget';
import ExplicitSchemeWidget   from './src/components/routing/ExplicitSchemeWidget';
import SchemeCompareWidget    from './src/components/routing/SchemeCompareWidget';
import DiffusiveWaveWidget    from './src/components/routing/DiffusiveWaveWidget';
import KinWaveExploreWidget   from './src/components/routing/KinWaveExploreWidget';
import KinematicFailureWidget from './src/components/routing/KinematicFailureWidget';
import WaterSurfaceSlopeWidget from './src/components/routing/WaterSurfaceSlopeWidget';
import DagVsChannelDiagram    from './src/components/routing/DagVsChannelDiagram';
import DiffusiveWaveDerivationWidget from './src/components/routing/DiffusiveWaveDerivationWidget';
import ConveyanceDepthWidget  from './src/components/routing/ConveyanceDepthWidget';
import GlobalDtTyrannyWidget  from './src/components/routing/GlobalDtTyrannyWidget';
import AdvectionSmearWidget   from './src/components/routing/AdvectionSmearWidget';
import CourantBlendWidget     from './src/components/routing/CourantBlendWidget';
import ModifiedEquationWidget from './src/components/routing/ModifiedEquationWidget';
import GridCharacteristicWidget from './src/components/routing/GridCharacteristicWidget';
import WaveCrossingWidget     from './src/components/routing/WaveCrossingWidget';
import AdaptiveDtWidget       from './src/components/routing/AdaptiveDtWidget';
import DunneHortonWidget      from './src/components/runoff/DunneHortonWidget';
import CallOrderDiagram       from './src/components/runoff/CallOrderDiagram';
import SatelliteChainWidget   from './src/components/runoff/SatelliteChainWidget';
import VSAEquationBuilderWidget from './src/components/runoff/VSAEquationBuilderWidget';
import VSAMapWidget           from './src/components/runoff/VSAMapWidget';
import GreenAmptWidget        from './src/components/runoff/GreenAmptWidget';
import RunoffDecompositionWidget from './src/components/runoff/RunoffDecompositionWidget';
import PerPolygonVSAWidget    from './src/components/runoff/PerPolygonVSAWidget';
import HandStageWidget        from './src/components/flood/HandStageWidget';
import Hand3DWidget           from './src/components/flood/Hand3DWidget';
import LeastCostWidget        from './src/components/flood/LeastCostWidget';
import CarveBedWidget         from './src/components/flood/CarveBedWidget';
import ReachWidget            from './src/components/flood/ReachWidget';
import RatingCurveWidget      from './src/components/flood/RatingCurveWidget';
import LevelsWidget           from './src/components/flood/LevelsWidget';
import SlotWidget             from './src/components/flood/SlotWidget';
import GorgeWidget            from './src/components/flood/GorgeWidget';
import GridToTreeWidget       from './src/components/tree/GridToTreeWidget';
import Tree3DWidget           from './src/components/tree/Tree3DWidget';
import FlattenOrderWidget     from './src/components/tree/FlattenOrderWidget';
import ThreeWalksWidget       from './src/components/tree/ThreeWalksWidget';
import LevelScheduleWidget    from './src/components/tree/LevelScheduleWidget';

export function useMDXComponents(components: MDXComponents): MDXComponents {
  return {
    DEMFlowWidget,
    DEM3DWidget,
    FlowAccumWidget,
    PitFillWidget,
    SlopeCalcWidget,
    FlowDirTeachWidget,
    PitTeachWidget,
    TopoAccumWidget,
    WatershedConceptWidget,
    BFSDelineateWidget,
    CatchmentMapWidget,
    WatershedExploreWidget,
    SaintVenantWidget,
    ManningCelerityWidget,
    FiniteDiffBuildupWidget,
    ExplicitSchemeWidget,
    SchemeCompareWidget,
    DiffusiveWaveWidget,
    KinWaveExploreWidget,
    KinematicFailureWidget,
    WaterSurfaceSlopeWidget,
    DagVsChannelDiagram,
    DiffusiveWaveDerivationWidget,
    ConveyanceDepthWidget,
    GlobalDtTyrannyWidget,
    AdvectionSmearWidget,
    CourantBlendWidget,
    ModifiedEquationWidget,
    GridCharacteristicWidget,
    WaveCrossingWidget,
    AdaptiveDtWidget,
    DunneHortonWidget,
    CallOrderDiagram,
    SatelliteChainWidget,
    VSAEquationBuilderWidget,
    VSAMapWidget,
    GreenAmptWidget,
    RunoffDecompositionWidget,
    PerPolygonVSAWidget,
    HandStageWidget,
    Hand3DWidget,
    LeastCostWidget,
    CarveBedWidget,
    ReachWidget,
    RatingCurveWidget,
    LevelsWidget,
    SlotWidget,
    GorgeWidget,
    GridToTreeWidget,
    Tree3DWidget,
    FlattenOrderWidget,
    ThreeWalksWidget,
    LevelScheduleWidget,
    ...components,
  };
}
