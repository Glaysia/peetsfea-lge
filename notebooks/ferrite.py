# ----------------------------------------------
# Script Recorded by Ansys Electronics Desktop Version 2025.2.0
# 15:22:12  Apr 17, 2026
# ----------------------------------------------
import ScriptEnv
ScriptEnv.Initialize("Ansoft.ElectronicsDesktop")
oDesktop.RestoreWindow()
oProject = oDesktop.SetActiveProject("Project64")
oDefinitionManager = oProject.GetDefinitionManager()
oDefinitionManager.AddMaterial(
	[
		"NAME:ferrite_asdf - Copy",
		"CoordinateSystemType:=", "Cartesian",
		"BulkOrSurfaceType:="	, 1,
		[
			"NAME:PhysicsTypes",
			"set:="			, ["Electromagnetic","Thermal","Structural"]
		],
		[
			"NAME:AttachedData",
			[
				"NAME:MatAppearanceData",
				"property_data:="	, "appearance_data",
				"Red:="			, 89,
				"Green:="		, 94,
				"Blue:="		, 107
			]
		],
		"permittivity:="	, "12",
		"permeability:="	, "pwlx($mu_r_real, Freq)",
		"conductivity:="	, "0.01",
		"magnetic_loss_tangent:=", "pwlx($mu_tand_m, Freq)",
		"thermal_conductivity:=", "4",
		"mass_density:="	, "4600",
		"specific_heat:="	, "750",
		"youngs_modulus:="	, "119000000000",
		"thermal_expansion_coefficient:=", "1e-05"
	])
oDesign = oProject.SetActiveDesign("type2_step_import")
oEditor = oDesign.SetActiveEditor("3D Modeler")
oEditor.MoveOrigin(
	[
		"NAME:Selections",
		"AllowRegionDependentPartSelectionForPMLCreation:=", True,
		"AllowRegionSelectionForPMLCreation:=", True,
		"Selections:="		, "Box1"
	], 
	[
		"NAME:Attributes",
		"MaterialValue:="	, "\"ferrite_asdf - Copy\"",
		"SolveInside:="		, True,
		"ShellElement:="	, False,
		"ShellElementThickness:=", "nan ",
		"ReferenceTemperature:=", "nan ",
		"IsMaterialEditable:="	, True,
		"IsSurfaceMaterialEditable:=", True,
		"UseMaterialAppearance:=", False,
		"IsLightweight:="	, False
	])
